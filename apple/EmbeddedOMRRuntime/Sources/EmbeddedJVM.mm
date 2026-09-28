// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
#import "EmbeddedJVM.h"
#include <jni.h>
#include <dlfcn.h>
#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>
#include <atomic>
#include <algorithm>
#include <chrono>
#include <memory>
#include <mutex>
#include <thread>
#include <mach/mach.h>
#include <TargetConditionals.h>

extern "C" void loadfunctions(void);

static JavaVM *embeddedVM = nullptr;
static bool startupAttempted = false;
static NSString *initializedResources;
static NSString *initializedSandbox;

@interface EmbeddedOMRCancellation () {
    std::atomic<bool> _requested;
}
- (jlong)nativeHandle;
@end

@implementation EmbeddedOMRCancellation
- (instancetype)init {
    self = [super init];
    if (self) _requested.store(false);
    return self;
}
- (void)cancel { _requested.store(true); }
- (BOOL)isCancelled { return _requested.load(); }
- (jlong)nativeHandle { return static_cast<jlong>(reinterpret_cast<intptr_t>(&_requested)); }
@end

static std::mutex activeCancellationMutex;
static EmbeddedOMRCancellation *activeCancellation;

class ActiveCancellationScope {
public:
    explicit ActiveCancellationScope(EmbeddedOMRCancellation *token) {
        std::lock_guard<std::mutex> lock(activeCancellationMutex);
        activeCancellation = token;
    }
    ~ActiveCancellationScope() {
        std::lock_guard<std::mutex> lock(activeCancellationMutex);
        activeCancellation = nil;
    }
};

static jboolean nativeCancellationRequested(JNIEnv *, jclass, jlong handle) {
    // Java polls only during the synchronous entry. The owning ObjC token is
    // retained through that entire call, including shutdown/timeout handling.
    auto *flag = reinterpret_cast<const std::atomic<bool> *>(static_cast<intptr_t>(handle));
    return flag && flag->load() ? JNI_TRUE : JNI_FALSE;
}

static jboolean nativeMixedPrimitiveArguments(JNIEnv *environment, jclass, jobject leadingObject,
        jint a, jint b, jint c, jint d, jint e, jint f, jint g, jint h,
        jboolean first, jboolean second, jboolean third, jint trailingInt, jobject trailingObject,
        jbyte negativeByte, jshort negativeShort, jchar highChar,
        jbyte positiveByte, jshort positiveShort, jchar maxChar, jlong wide, jbyteArray payload) {
    const bool scalars = a == 1 && b == 2 && c == 3 && d == 4 && e == 5 && f == 6 && g == 7 && h == 8
        && first == JNI_TRUE && second == JNI_FALSE && third == JNI_TRUE && trailingInt == 0x13579bdf
        && negativeByte == -128 && negativeShort == -32768 && highChar == 0xfedc
        && positiveByte == 127 && positiveShort == 32767 && maxChar == 0xffff
        && wide == 0x0123456789abcdefLL;
    // A broken stack layout may corrupt the trailing object slot. Check every
    // scalar first and avoid dereferencing that slot if the ABI check failed.
    if (!scalars || !environment->IsSameObject(leadingObject, trailingObject)
        || !payload || environment->GetArrayLength(payload) != 3) return JNI_FALSE;
    jbyte bytes[3] = {};
    environment->GetByteArrayRegion(payload, 0, 3, bytes);
    return !environment->ExceptionCheck() && bytes[0] == -128 && bytes[1] == 0 && bytes[2] == 127
        ? JNI_TRUE : JNI_FALSE;
}

static jboolean nativeMixedInstanceArguments(JNIEnv *environment, jobject receiver, jobject leadingObject,
        jint a, jint b, jint c, jint d, jint e, jint f, jint g, jint h,
        jboolean first, jboolean second, jboolean third, jint trailingInt, jobject trailingObject,
        jbyte negativeByte, jshort negativeShort, jchar highChar,
        jbyte positiveByte, jshort positiveShort, jchar maxChar, jlong wide, jbyteArray payload) {
    return nativeMixedPrimitiveArguments(environment, nullptr, leadingObject, a, b, c, d, e, f, g, h,
        first, second, third, trailingInt, trailingObject, negativeByte, negativeShort, highChar,
        positiveByte, positiveShort, maxChar, wide, payload)
        && environment->IsSameObject(receiver, leadingObject) ? JNI_TRUE : JNI_FALSE;
}

// Process-wide samples include the host UI, VM, native OCR, and this sampler.
// A sampled maximum is not the operating system's exact high-water mark.
class ProbeMemorySampler {
    std::atomic<bool> stopped{false};
    std::thread worker;
    uint64_t baselineResident = 0, baselineFootprint = 0;
    uint64_t peakResident = 0, peakFootprint = 0, samples = 0, failedSamples = 0;

    void sample() {
        task_vm_info_data_t info = {};
        mach_msg_type_number_t count = TASK_VM_INFO_COUNT;
        kern_return_t status = task_info(mach_task_self(), TASK_VM_INFO,
                                         reinterpret_cast<task_info_t>(&info), &count);
        if (status != KERN_SUCCESS || count < TASK_VM_INFO_REV1_COUNT) {
            ++failedSamples;
            return;
        }
        if (samples == 0) {
            baselineResident = info.resident_size;
            baselineFootprint = info.phys_footprint;
        }
        ++samples;
        peakResident = std::max(peakResident, static_cast<uint64_t>(info.resident_size));
        peakFootprint = std::max(peakFootprint, static_cast<uint64_t>(info.phys_footprint));
    }

    void stop() {
        stopped.store(true);
        if (worker.joinable()) worker.join();
    }

public:
    ProbeMemorySampler() {
        sample();
        worker = std::thread([this] {
            while (!stopped.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(50));
                if (!stopped.load()) sample();
            }
        });
    }
    ~ProbeMemorySampler() { stop(); }

    NSDictionary *report() {
        stop();
        sample();
        return @{
            @"measurement": @"Darwin task_info TASK_VM_INFO; sampled process-wide values",
            @"platform": TARGET_OS_SIMULATOR ? @"ios-simulator" : @"ios-device",
            @"samplingIntervalMilliseconds": @50,
            @"sampleCount": @(samples), @"failedSampleCount": @(failedSamples),
            @"baselineResidentBytes": @(baselineResident),
            @"peakSampledResidentBytes": @(peakResident),
            @"baselinePhysicalFootprintBytes": @(baselineFootprint),
            @"peakSampledPhysicalFootprintBytes": @(peakFootprint),
        };
    }
};

@interface EmbeddedJVM ()
+ (nullable NSString *)invokeWithResourceRoot:(NSString *)resourceRoot sandbox:(NSString *)sandbox
                                 entryClass:(const char *)entryClass method:(const char *)method
                              firstArgument:(NSString *)firstArgument secondArgument:(NSString *)secondArgument
                                cancellation:(nullable EmbeddedOMRCancellation *)cancellation error:(NSError **)error;
@end

static void setError(NSError **error, NSString *message) {
    NSLog(@"EMBEDDED_OMR_PROBE_FAILURE %@", message);
    if (error) {
        *error = [NSError errorWithDomain:@"com.notelite.embeddedprobe" code:1
                                userInfo:@{NSLocalizedDescriptionKey: message}];
    }
}

static NSString *canonicalDirectory(NSString *path, NSError **error) {
    char *resolved = realpath(path.fileSystemRepresentation, nullptr);
    if (!resolved) {
        const int failure = errno;
        if (error) *error = [NSError errorWithDomain:NSPOSIXErrorDomain code:failure
                                           userInfo:@{NSFilePathErrorKey: path}];
        return nil;
    }
    NSString *canonical = [NSFileManager.defaultManager stringWithFileSystemRepresentation:resolved
                                                                                    length:strlen(resolved)];
    free(resolved);
    BOOL directory = NO;
    if (![NSFileManager.defaultManager fileExistsAtPath:canonical isDirectory:&directory] || !directory) {
        if (error) *error = [NSError errorWithDomain:NSPOSIXErrorDomain code:ENOTDIR
                                           userInfo:@{NSFilePathErrorKey: path}];
        return nil;
    }
    return canonical;
}

static NSString *javaString(JNIEnv *environment, jstring string) {
    if (!string) return nil;
    const jchar *characters = environment->GetStringChars(string, nullptr);
    if (!characters) return nil;
    NSString *result = [[NSString alloc] initWithCharacters:(const unichar *)characters
                                                    length:environment->GetStringLength(string)];
    environment->ReleaseStringChars(string, characters);
    return result;
}

static jstring newJavaString(JNIEnv *environment, NSString *string) {
    std::vector<jchar> characters(string.length);
    [string getCharacters:(unichar *)characters.data() range:NSMakeRange(0, string.length)];
    return environment->NewString(characters.data(), (jsize)characters.size());
}

static NSString *pendingException(JNIEnv *environment) {
    jthrowable exception = environment->ExceptionOccurred();
    if (!exception) return nil;
    environment->ExceptionDescribe(); // Include the original Java stack in simulator logs.
    environment->ExceptionClear();
    jclass type = environment->GetObjectClass(exception);
    jmethodID describe = environment->GetMethodID(type, "toString", "()Ljava/lang/String;");
    jstring value = describe ? (jstring)environment->CallObjectMethod(exception, describe) : nullptr;
    NSString *message = javaString(environment, value) ?: @"Java exception (see native log)";
    if (environment->ExceptionCheck()) environment->ExceptionClear();
    if (value) environment->DeleteLocalRef(value);
    environment->DeleteLocalRef(type);
    environment->DeleteLocalRef(exception);
    return message;
}

@implementation EmbeddedJVM
+ (NSString *)runWithResourceRoot:(NSString *)resourceRoot sandbox:(NSString *)sandbox error:(NSError **)error {
    return [self invokeWithResourceRoot:resourceRoot sandbox:sandbox entryClass:"EmbeddedNativeProbe"
        method:"run" firstArgument:resourceRoot secondArgument:sandbox cancellation:nil error:error];
}

+ (NSString *)recognizeWithResourceRoot:(NSString *)resourceRoot sandbox:(NSString *)sandbox
                                  input:(NSString *)input error:(NSError **)error {
    return [self recognizeWithResourceRoot:resourceRoot sandbox:sandbox input:input
                             cancellation:[EmbeddedOMRCancellation new] error:error];
}

+ (NSString *)recognizeWithResourceRoot:(NSString *)resourceRoot sandbox:(NSString *)sandbox
                                  input:(NSString *)input cancellation:(EmbeddedOMRCancellation *)cancellation
                                  error:(NSError **)error {
    return [self invokeWithResourceRoot:resourceRoot sandbox:sandbox entryClass:"com/notelite/omr/EmbeddedOmrEngine"
        method:"recognizeToJSONWithNativeCancellation" firstArgument:sandbox secondArgument:input
        cancellation:cancellation error:error];
}

+ (void)cancelCurrentRecognition {
    EmbeddedOMRCancellation *token;
    {
        // This lock protects only an object reference; it is never held during JNI work.
        std::lock_guard<std::mutex> lock(activeCancellationMutex);
        token = activeCancellation;
    }
    [token cancel];
}

+ (NSString *)invokeWithResourceRoot:(NSString *)resourceRoot sandbox:(NSString *)sandbox
                          entryClass:(const char *)entryClass method:(const char *)method
                       firstArgument:(NSString *)firstArgument secondArgument:(NSString *)secondArgument
                         cancellation:(EmbeddedOMRCancellation *)cancellation error:(NSError **)error {
    __attribute__((objc_precise_lifetime)) EmbeddedOMRCancellation *ownedCancellation = cancellation;
    const BOOL recognition = ownedCancellation != nil;
    @synchronized (self) {
        std::unique_ptr<ProbeMemorySampler> memory;
        if (!recognition) memory = std::make_unique<ProbeMemorySampler>();
        std::unique_ptr<ActiveCancellationScope> activeScope;
        if (recognition) activeScope = std::make_unique<ActiveCancellationScope>(ownedCancellation);
        if (ownedCancellation.isCancelled) {
            if (error) *error = [NSError errorWithDomain:NSCocoaErrorDomain code:NSUserCancelledError userInfo:nil];
            return nil;
        }
        NSFileManager *files = NSFileManager.defaultManager;
        if (!embeddedVM && ![files createDirectoryAtPath:sandbox
              withIntermediateDirectories:YES attributes:nil error:error]) return nil;
        // iOS exposes equivalent /var and /private/var sandbox paths. Compare
        // existing physical directories and pass those identities to Java too.
        sandbox = canonicalDirectory(sandbox, error);
        if (!sandbox) return nil;
        resourceRoot = canonicalDirectory(resourceRoot, error);
        if (!resourceRoot) return nil;
        if (embeddedVM && (![initializedResources isEqualToString:resourceRoot]
                           || ![initializedSandbox isEqualToString:sandbox])) {
            setError(error, @"The existing JVM belongs to a different resource directory or sandbox");
            return nil;
        }
        if (![files createDirectoryAtPath:[sandbox stringByAppendingPathComponent:@"tmp"]
              withIntermediateDirectories:YES attributes:nil error:error]) return nil;
        firstArgument = recognition ? sandbox : resourceRoot;
        if (!recognition) secondArgument = sandbox;

        NSString *runtime = [resourceRoot stringByAppendingPathComponent:@"runtime"];
        NSString *jarDirectory = [resourceRoot stringByAppendingPathComponent:@"java"];
        NSString *assets = [resourceRoot stringByAppendingPathComponent:@"assets"];
        NSString *tessdata = [resourceRoot stringByAppendingPathComponent:@"tessdata"];
        if (![files fileExistsAtPath:[runtime stringByAppendingPathComponent:@"lib/modules"]]) {
            setError(error, @"The compiled target Java module image is missing");
            return nil;
        }
        NSArray<NSString *> *names = [[files contentsOfDirectoryAtPath:jarDirectory error:error]
                                      sortedArrayUsingSelector:@selector(compare:)];
        if (!names) return nil;
        NSMutableArray<NSString *> *jars = [NSMutableArray array];
        for (NSString *name in names) {
            if ([name.pathExtension isEqualToString:@"jar"])
                [jars addObject:[jarDirectory stringByAppendingPathComponent:name]];
        }
        if (jars.count == 0) {
            setError(error, @"The bundled Java engine JARs are missing");
            return nil;
        }
        JNIEnv *environment = nullptr;
        bool detach = false;
        if (!embeddedVM) {
            if (startupAttempted) {
                setError(error, @"The JVM failed to initialize; restart the probe app before retrying");
                return nil;
            }
            startupAttempted = true;
            setenv("JAVA_HOME", runtime.fileSystemRepresentation, 1);
            setenv("TESSDATA_PREFIX", tessdata.fileSystemRepresentation, 1);
            // Retain/export actual static native symbols before the VM resolves built-in libraries.
            loadfunctions();
            for (const char *symbol : {"JNI_OnLoad_jnijavacpp", "JNI_OnLoad_jnileptonica",
                                       "JNI_OnLoad_jnitesseract"}) {
                if (!dlsym(RTLD_DEFAULT, symbol)) {
                    setError(error, [NSString stringWithFormat:@"Static native entry is missing: %s", symbol]);
                    return nil;
                }
            }
            NSArray<NSString *> *arguments = @[
                @"-Xint", @"-Xms64m", @"-Xmx768m", @"-Xss2m", @"-XX:+UseSerialGC", @"-XX:-UsePerfData",
                [@"-Djava.home=" stringByAppendingString:runtime],
                [@"-Djava.class.path=" stringByAppendingString:[jars componentsJoinedByString:@":"]],
                [@"-Dsun.boot.library.path=" stringByAppendingString:[runtime stringByAppendingPathComponent:@"lib"]],
                [@"-Djava.library.path=" stringByAppendingString:[runtime stringByAppendingPathComponent:@"lib"]],
                @"-Djava.awt.headless=true", @"-Dfile.encoding=UTF-8",
                @"-Dflatlaf.useNativeLibrary=false",
                @"-Dnotelite.omr.jniHost=true",
                [@"-Dnotelite.appHome=" stringByAppendingString:sandbox],
                [@"-Duser.home=" stringByAppendingString:sandbox],
                [@"-Djava.io.tmpdir=" stringByAppendingString:[sandbox stringByAppendingPathComponent:@"tmp"]],
                [@"-Dnotelite.omr.fontDirectory=" stringByAppendingString:assets],
                [@"-Dnotelite.omr.defaultFontFile=" stringByAppendingString:[assets stringByAppendingPathComponent:@"FinaleJazzText.otf"]],
                @"-Dnotelite.omr.defaultFontFace=FinaleJazzText",
                @"-Dorg.bytedeco.javacpp.platform=ios-arm64",
                @"--add-exports=java.desktop/sun.awt.image=ALL-UNNAMED",
                @"--enable-native-access=ALL-UNNAMED",
                [@"-XX:ErrorFile=" stringByAppendingString:[sandbox stringByAppendingPathComponent:@"hs_err_pid%p.log"]]
            ];
            std::vector<std::string> values;
            for (NSString *argument in arguments) values.emplace_back(argument.UTF8String);
            std::vector<JavaVMOption> options(values.size());
            for (size_t index = 0; index < values.size(); index++) {
                options[index].optionString = values[index].data();
                options[index].extraInfo = nullptr;
            }
            JavaVMInitArgs configuration = {};
            configuration.version = JNI_VERSION_1_8;
            configuration.nOptions = (jint)options.size();
            configuration.options = options.data();
            configuration.ignoreUnrecognized = JNI_FALSE;
            NSLog(@"EMBEDDED_OMR_PROBE_STAGE creating-zero-vm");
            const jint status = JNI_CreateJavaVM(&embeddedVM, (void **)&environment, &configuration);
            if (status != JNI_OK || !environment) {
                embeddedVM = nullptr;
                setError(error, [NSString stringWithFormat:@"JNI_CreateJavaVM failed with status %d", status]);
                return nil;
            }
            detach = true;
            initializedResources = [resourceRoot copy];
            initializedSandbox = [sandbox copy];
        } else {
            const jint state = embeddedVM->GetEnv((void **)&environment, JNI_VERSION_1_8);
            if (state == JNI_EDETACHED) {
                if (embeddedVM->AttachCurrentThread((void **)&environment, nullptr) != JNI_OK) {
                    setError(error, @"Could not attach the probe worker to the JVM");
                    return nil;
                }
                detach = true;
            } else if (state != JNI_OK) {
                setError(error, @"Could not access the existing JVM");
                return nil;
            }
        }

        if (ownedCancellation.isCancelled) {
            if (error) *error = [NSError errorWithDomain:NSCocoaErrorDomain code:NSUserCancelledError userInfo:nil];
            if (detach) embeddedVM->DetachCurrentThread();
            return nil;
        }

        NSLog(@"EMBEDDED_OMR_PROBE_STAGE java-component-and-score-tests");
        NSString *result = nil;
        jclass probe = environment->FindClass(entryClass);
        NSString *exception = pendingException(environment);
        if (probe && !exception) {
            if (recognition) {
                JNINativeMethod callback = {const_cast<char *>("nativeCancellationRequested"),
                    const_cast<char *>("(J)Z"), reinterpret_cast<void *>(&nativeCancellationRequested)};
                if (environment->RegisterNatives(probe, &callback, 1) != JNI_OK) {
                    exception = pendingException(environment) ?: @"Could not register request cancellation callback";
                }
            } else {
                jclass argumentsProbe = environment->FindClass("PortabilityProbe");
                exception = pendingException(environment);
                if (argumentsProbe && !exception) {
                    const char *signature = "(Ljava/lang/Object;IIIIIIIIZZZILjava/lang/Object;BSCBSCJ[B)Z";
                    JNINativeMethod callbacks[] = {
                        {const_cast<char *>("mixedPrimitiveArguments"), const_cast<char *>(signature),
                         reinterpret_cast<void *>(&nativeMixedPrimitiveArguments)},
                        {const_cast<char *>("mixedInstanceArguments"), const_cast<char *>(signature),
                         reinterpret_cast<void *>(&nativeMixedInstanceArguments)}
                    };
                    if (environment->RegisterNatives(argumentsProbe, callbacks, 2) != JNI_OK) {
                        exception = pendingException(environment) ?: @"Could not register native argument probe";
                    }
                }
                if (argumentsProbe) environment->DeleteLocalRef(argumentsProbe);
            }
            jmethodID run = nullptr;
            if (!exception) {
                run = environment->GetStaticMethodID(probe, method,
                    recognition ? "(Ljava/lang/String;Ljava/lang/String;J)Ljava/lang/String;"
                                : "(Ljava/lang/String;Ljava/lang/String;)Ljava/lang/String;");
                exception = pendingException(environment);
            }
            if (run && !exception) {
                jstring resources = newJavaString(environment, firstArgument);
                jstring root = newJavaString(environment, secondArgument);
                if (!environment->ExceptionCheck()) {
                    jstring report = recognition
                        ? (jstring)environment->CallStaticObjectMethod(probe, run, resources, root, [ownedCancellation nativeHandle])
                        : (jstring)environment->CallStaticObjectMethod(probe, run, resources, root);
                    exception = pendingException(environment);
                    if (!exception) result = javaString(environment, report);
                    if (report) environment->DeleteLocalRef(report);
                } else {
                    exception = pendingException(environment);
                }
                if (resources) environment->DeleteLocalRef(resources);
                if (root) environment->DeleteLocalRef(root);
            }
            environment->DeleteLocalRef(probe);
        }
        if (ownedCancellation.isCancelled && result) {
            // Preserve the known output directory so the caller can discard a canceled job.
            // A timeout may still have active workers: retain its status and files for diagnosis.
            NSMutableDictionary *report = [NSJSONSerialization JSONObjectWithData:[result dataUsingEncoding:NSUTF8StringEncoding]
                                                                          options:NSJSONReadingMutableContainers error:nil];
            if ([report isKindOfClass:NSMutableDictionary.class]
                && ![report[@"status"] isEqual:@"TIMED_OUT"]) {
                report[@"status"] = @"CANCELLED";
                report[@"musicXML"] = @[];
                report[@"midi"] = @[];
                NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:nil];
                if (data) result = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
            }
        } else if (!result) setError(error, exception ?: @"Java engine returned no result");
        if (memory && result) {
            NSMutableDictionary *report = [NSJSONSerialization JSONObjectWithData:[result dataUsingEncoding:NSUTF8StringEncoding]
                                                                          options:NSJSONReadingMutableContainers error:nil];
            if ([report isKindOfClass:NSMutableDictionary.class]) {
                report[@"nativeMemory"] = memory->report();
                NSData *data = [NSJSONSerialization dataWithJSONObject:report options:0 error:nil];
                if (data) result = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
            }
        }
        // Keep the same VM alive for the host app's lifetime. No process launch or DestroyJavaVM.
        if (detach) embeddedVM->DetachCurrentThread();
        return result;
    }
}
@end
