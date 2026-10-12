// Copyright 2022 The Chromium Authors
// Derived declarations and descriptor setup from Chromium's BSD-licensed test:
// https://chromium.googlesource.com/chromium/src/+/b24245976fd032dfbc62673317b26a5ecd802b59/ui/display/mac/test/virtual_display_util_mac.mm
// See ui-test-display-LICENSE.txt. This executable is CI infrastructure only.
// CGVirtualDisplay is undocumented; it must never be linked into NoteLite.
#import <AppKit/AppKit.h>
#import <CoreGraphics/CoreGraphics.h>
#import <Foundation/Foundation.h>
#import <signal.h>
#import <string.h>
#import <unistd.h>

@interface CGVirtualDisplayDescriptor : NSObject
@property(nonatomic) unsigned int vendorID;
@property(nonatomic) unsigned int productID;
@property(nonatomic) unsigned int serialNum;
@property(nonatomic) unsigned int serialNumber;
@property(strong, nonatomic) NSString *name;
@property(nonatomic) CGSize sizeInMillimeters;
@property(nonatomic) unsigned int maxPixelsWide;
@property(nonatomic) unsigned int maxPixelsHigh;
@property(nonatomic) CGPoint redPrimary;
@property(nonatomic) CGPoint greenPrimary;
@property(nonatomic) CGPoint bluePrimary;
@property(nonatomic) CGPoint whitePoint;
@property(strong, nonatomic) id queue;
@end

@interface CGVirtualDisplayMode : NSObject
- (id)initWithWidth:(unsigned int)width height:(unsigned int)height refreshRate:(double)rate;
@end

@interface CGVirtualDisplaySettings : NSObject
@property(strong, nonatomic) NSArray *modes;
@property(nonatomic) unsigned int hiDPI;
@property(nonatomic) unsigned int rotation;
@end

@interface CGVirtualDisplay : NSObject
@property(readonly, nonatomic) unsigned int displayID;
- (id)initWithDescriptor:(id)descriptor;
- (BOOL)applySettings:(id)settings;
@end

static CGVirtualDisplay *heldDisplay;
static NSMutableArray<NSDictionary *> *originalDisplays;

static void writeJSON(NSDictionary *value, NSString *path) {
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
    if (!data || ![data writeToFile:path options:NSDataWritingAtomic error:&error]) {
        fprintf(stderr, "Could not write display evidence: %s\n", error.localizedDescription.UTF8String);
        exit(5);
    }
}

static NSArray *screens(void) {
    NSMutableArray *result = [NSMutableArray array];
    for (NSScreen *screen in NSScreen.screens) {
        NSRect frame = screen.frame, visible = screen.visibleFrame;
        [result addObject:@{@"id": screen.deviceDescription[@"NSScreenNumber"],
                           @"frame": @{@"x": @(frame.origin.x), @"y": @(frame.origin.y), @"width": @(frame.size.width), @"height": @(frame.size.height)},
                           @"visibleFrame": @{@"x": @(visible.origin.x), @"y": @(visible.origin.y), @"width": @(visible.size.width), @"height": @(visible.size.height)},
                           @"scale": @(screen.backingScaleFactor)}];
    }
    return result;
}

static void restoreOriginalDisplays(void) {
    CGDisplayConfigRef configuration = NULL;
    if (CGBeginDisplayConfiguration(&configuration) == kCGErrorSuccess) {
        BOOL success = YES;
        for (NSDictionary *value in originalDisplays) {
            CGError result = CGConfigureDisplayOrigin(configuration, [value[@"id"] unsignedIntValue],
                                                      [value[@"x"] intValue], [value[@"y"] intValue]);
            if (result != kCGErrorSuccess) success = NO;
        }
        if (success) CGCompleteDisplayConfiguration(configuration, kCGConfigureForSession);
        else CGCancelDisplayConfiguration(configuration);
    }
    heldDisplay = nil;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2 || strcmp(getenv("GITHUB_ACTIONS") ?: "", "true") != 0) {
            fprintf(stderr, "This helper runs only on disposable GitHub Actions macOS runners; provide a diagnostic JSON path.\n");
            return 2;
        }
        NSString *evidencePath = [NSString stringWithUTF8String:argv[1]];
        if (!NSClassFromString(@"CGVirtualDisplay") || !NSClassFromString(@"CGVirtualDisplayDescriptor")) {
            writeJSON(@{@"ready": @NO, @"reason": @"CGVirtualDisplay unavailable", @"productionIncluded": @NO}, evidencePath);
            return 3;
        }
        [NSApplication sharedApplication];
        [NSApp setActivationPolicy:NSApplicationActivationPolicyProhibited];
        CGDirectDisplayID originalIDs[32];
        uint32_t originalCount = 0;
        if (CGGetActiveDisplayList(32, originalIDs, &originalCount) != kCGErrorSuccess) return 3;
        originalDisplays = [NSMutableArray array];
        for (uint32_t index = 0; index < originalCount; index++) {
            CGRect bounds = CGDisplayBounds(originalIDs[index]);
            [originalDisplays addObject:@{@"id": @(originalIDs[index]), @"x": @(bounds.origin.x), @"y": @(bounds.origin.y)}];
        }
        const unsigned int width = 1800, height = 1800;
        CGVirtualDisplayDescriptor *descriptor = [[CGVirtualDisplayDescriptor alloc] init];
        descriptor.queue = dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0);
        descriptor.name = @"NoteLite CI native UI display";
        descriptor.whitePoint = CGPointMake(0.3125, 0.3291);
        descriptor.bluePrimary = CGPointMake(0.1494, 0.0557);
        descriptor.greenPrimary = CGPointMake(0.2559, 0.6983);
        descriptor.redPrimary = CGPointMake(0.6797, 0.3203);
        descriptor.maxPixelsWide = width;
        descriptor.maxPixelsHigh = height;
        descriptor.sizeInMillimeters = CGSizeMake(25.4 * width / 100, 25.4 * height / 100);
        descriptor.vendorID = 505;
        descriptor.productID = 0;
        descriptor.serialNum = (unsigned int)getpid();
        descriptor.serialNumber = descriptor.serialNum;
        heldDisplay = [[CGVirtualDisplay alloc] initWithDescriptor:descriptor];
        CGVirtualDisplaySettings *settings = [[CGVirtualDisplaySettings alloc] init];
        settings.hiDPI = 0;
        settings.rotation = 0;
        settings.modes = @[[[CGVirtualDisplayMode alloc] initWithWidth:width height:height refreshRate:60]];
        if (!heldDisplay || ![heldDisplay applySettings:settings]) {
            writeJSON(@{@"ready": @NO, @"reason": @"Virtual display creation/settings rejected", @"productionIncluded": @NO}, evidencePath);
            heldDisplay = nil;
            return 3;
        }
        CGDirectDisplayID testDisplay = heldDisplay.displayID;
        NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:15];
        while (!CGDisplayIsOnline(testDisplay) && deadline.timeIntervalSinceNow > 0) {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
        }
        CGDisplayConfigRef configuration = NULL;
        CGError result = CGBeginDisplayConfiguration(&configuration);
        if (result == kCGErrorSuccess) {
            for (NSDictionary *value in originalDisplays) {
                result = CGConfigureDisplayOrigin(configuration, [value[@"id"] unsignedIntValue],
                                                  width + 32 + [value[@"x"] intValue], [value[@"y"] intValue]);
                if (result != kCGErrorSuccess) break;
            }
            if (result == kCGErrorSuccess) result = CGConfigureDisplayOrigin(configuration, testDisplay, 0, 0);
            if (result == kCGErrorSuccess) result = CGCompleteDisplayConfiguration(configuration, kCGConfigureForSession);
            else CGCancelDisplayConfiguration(configuration);
        }
        if (result != kCGErrorSuccess) {
            writeJSON(@{@"ready": @NO, @"reason": @"Native primary display configuration rejected", @"cgError": @(result), @"productionIncluded": @NO}, evidencePath);
            restoreOriginalDisplays();
            return 4;
        }
        deadline = [NSDate dateWithTimeIntervalSinceNow:15];
        BOOL ready = NO;
        do {
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
            for (NSScreen *screen in NSScreen.screens) {
                if ([screen.deviceDescription[@"NSScreenNumber"] unsignedIntValue] == testDisplay &&
                    screen.visibleFrame.size.width >= 1472 && screen.visibleFrame.size.height >= 1504 &&
                    CGMainDisplayID() == testDisplay) ready = YES;
            }
        } while (!ready && deadline.timeIntervalSinceNow > 0);
        writeJSON(@{@"ready": @(ready), @"displayID": @(testDisplay), @"mainDisplayID": @(CGMainDisplayID()),
                    @"requestedWidth": @(width), @"requestedHeight": @(height), @"hiDPI": @NO,
                    @"nativeWindowServerDisplay": @YES, @"virtualTestInfrastructure": @YES,
                    @"productionIncluded": @NO, @"screens": screens(),
                    @"chromiumReferenceCommit": @"b24245976fd032dfbc62673317b26a5ecd802b59"}, evidencePath);
        if (!ready) { restoreOriginalDisplays(); return 4; }
        signal(SIGTERM, SIG_IGN);
        signal(SIGINT, SIG_IGN);
        dispatch_source_t termination = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
        dispatch_source_t interruption = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGINT, 0, dispatch_get_main_queue());
        dispatch_source_set_event_handler(termination, ^{ restoreOriginalDisplays(); exit(0); });
        dispatch_source_set_event_handler(interruption, ^{ restoreOriginalDisplays(); exit(0); });
        dispatch_resume(termination);
        dispatch_resume(interruption);
        [NSApp run];
    }
}
