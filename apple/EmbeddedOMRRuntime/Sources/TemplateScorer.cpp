// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
// Scalar scoring follows Template.java. Keep arithmetic and point order exact.
#include "TemplateScorer.hpp"
#include <atomic>
#include <cfloat>
#include <cstring>
#include <limits>
#include <new>
#include <vector>

#ifdef __FAST_MATH__
#error "Template scoring requires strict binary64 arithmetic (no fast-math)"
#endif
#ifdef __clang__
#pragma clang fp contract(off)
#pragma clang fp reassociate(off)
#endif
static_assert(sizeof(double) == 8 && std::numeric_limits<double>::is_iec559,
              "Template scoring requires IEEE754 binary64");
static_assert(FLT_EVAL_METHOD == 0, "Extended-precision evaluation is unsupported");
static_assert(std::numeric_limits<std::int32_t>::min() == (-2147483647 - 1));
static_assert(sizeof(jshort) == sizeof(std::int16_t));

namespace notelite::template_scoring {
namespace {
std::int32_t signed_bits(std::uint32_t value) noexcept {
    std::int32_t result;
    std::memcpy(&result, &value, sizeof(result));
    return result;
}
std::int32_t add(std::int32_t a, std::int32_t b) noexcept {
    return signed_bits(static_cast<std::uint32_t>(a) + static_cast<std::uint32_t>(b));
}
std::int32_t subtract(std::int32_t a, std::int32_t b) noexcept {
    return signed_bits(static_cast<std::uint32_t>(a) - static_cast<std::uint32_t>(b));
}
bool read_point(const std::int16_t* storage, Geometry geometry, const Point& point,
                std::int32_t left, std::int32_t top, std::int32_t& actual) noexcept {
    const std::int32_t nx = add(left, point.x);
    const std::int32_t ny = add(top, point.y);
    if (nx < 0 || nx >= geometry.width || ny < 0 || ny >= geometry.height) return false;
    const std::size_t index = static_cast<std::size_t>(geometry.offset)
        + static_cast<std::size_t>(ny) * static_cast<std::size_t>(geometry.stride)
        + static_cast<std::size_t>(nx);
    actual = storage[index]; // Sign extension is the Java Table.Short behavior.
    return actual != -1;     // VALUE_UNKNOWN is ignored by both Java evaluators.
}
} // namespace

bool Geometry::valid_for(std::size_t storage_count) const noexcept {
    if (width < 0 || height < 0 || stride < 0 || offset < 0 || stride < width) return false;
    if (width == 0 || height == 0) return static_cast<std::size_t>(offset) <= storage_count;
    // Products of these nonnegative signed-32 fields fit unsigned 64 bits.
    const std::uint64_t last = static_cast<std::uint64_t>(offset)
        + static_cast<std::uint64_t>(height - 1) * static_cast<std::uint64_t>(stride)
        + static_cast<std::uint64_t>(width - 1);
    return last < storage_count;
}

double evaluate(const std::int16_t* storage, Geometry geometry,
                const Point* points, std::size_t point_count, Weights weights,
                std::int32_t x, std::int32_t y,
                std::int32_t offset_x, std::int32_t offset_y) noexcept {
    const std::int32_t left = subtract(x, offset_x);
    const std::int32_t top = subtract(y, offset_y);
    double total = 0.0;
    double sum_weights = 0.0;
    for (std::size_t i = 0; i < point_count; ++i) {
        const Point& point = points[i];
        std::int32_t actual = 0;
        if (!read_point(storage, geometry, point, left, top, actual)) continue;
        const double weight = point.distance == 0.0 ? weights.foreground
                            : point.distance > 0.0 ? weights.background : weights.hole;
        const double distance = ((actual == 0) == (point.distance == 0.0)) ? 0.0 : 1.0;
        // Preserve the original point order and independent multiply/add rounding.
        const double contribution = weight * distance;
        total = total + contribution;
        sum_weights = sum_weights + weight;
    }
    return sum_weights == 0.0 ? std::numeric_limits<double>::max() : total / sum_weights;
}

double evaluate_hole(const std::int16_t* storage, Geometry geometry,
                     const Point* points, std::size_t point_count,
                     std::int32_t x, std::int32_t y,
                     std::int32_t offset_x, std::int32_t offset_y) noexcept {
    const std::int32_t left = subtract(x, offset_x);
    const std::int32_t top = subtract(y, offset_y);
    std::int32_t expected_holes = 0;
    std::int32_t actual_holes = 0;
    for (std::size_t i = 0; i < point_count; ++i) {
        const Point& point = points[i];
        std::int32_t actual = 0;
        if (!read_point(storage, geometry, point, left, top, actual)) continue;
        if (point.distance < 0.0) {
            ++expected_holes;
            if (actual != 0) ++actual_holes;
        }
    }
    return expected_holes == 0 ? 0.0
         : static_cast<double>(actual_holes) / static_cast<double>(expected_holes);
}
} // namespace notelite::template_scoring

namespace {
namespace scorer = notelite::template_scoring;
struct PointFields {
    jclass type = nullptr;
    jfieldID x = nullptr;
    jfieldID y = nullptr;
    jfieldID distance = nullptr;
};
PointFields point_fields;
thread_local std::vector<scorer::Point> point_buffer;
std::atomic<jlong> call_count{0}, pin_count{0}, release_count{0}, copy_count{0};

void fail(JNIEnv* env, const char* type, const char* message) {
    if (env->ExceptionCheck()) return;
    jclass cls = env->FindClass(type);
    if (cls != nullptr) { env->ThrowNew(cls, message); env->DeleteLocalRef(cls); }
}

class CriticalShorts final {
    JNIEnv* env;
    jshortArray array;
public:
    jboolean copied = JNI_FALSE;
    jshort* values;
    CriticalShorts(JNIEnv* e, jshortArray a) : env(e), array(a),
        values(static_cast<jshort*>(e->GetPrimitiveArrayCritical(a, &copied))) {}
    ~CriticalShorts() {
        if (values != nullptr) {
            env->ReleasePrimitiveArrayCritical(array, values, JNI_ABORT);
            // Diagnostic work happens only after leaving the critical region.
            release_count.fetch_add(1, std::memory_order_relaxed);
        }
    }
    CriticalShorts(const CriticalShorts&) = delete;
    CriticalShorts& operator=(const CriticalShorts&) = delete;
};

double score(JNIEnv* env, jshortArray values, scorer::Geometry geometry,
             jobjectArray points, jint x, jint y, jint offset_x, jint offset_y,
             scorer::Weights weights, bool holes_only) {
    call_count.fetch_add(1, std::memory_order_relaxed);
    const double empty_result = holes_only ? 0.0 : std::numeric_limits<double>::max();
    if (values == nullptr || points == nullptr) {
        fail(env, "java/lang/NullPointerException", "distance storage and point snapshot are required");
        return empty_result;
    }
    if (!geometry.valid_for(static_cast<std::size_t>(env->GetArrayLength(values)))) {
        fail(env, "java/lang/IllegalArgumentException", "invalid distance storage geometry");
        return empty_result;
    }
    const jsize count = env->GetArrayLength(points);
    try { point_buffer.resize(static_cast<std::size_t>(count)); }
    catch (const std::bad_alloc&) {
        fail(env, "java/lang/OutOfMemoryError", "point snapshot allocation failed");
        return empty_result;
    }
    // Each actual PixelDistance[] is a fresh Java snapshot. Refresh every scalar
    // on each invocation; getKeyPoints() permits replacement and order changes.
    // The cached field IDs and global class were prepared before workers start.
    for (jsize i = 0; i < count; ++i) {
        jobject point = env->GetObjectArrayElement(points, i);
        if (point == nullptr) {
            fail(env, "java/lang/NullPointerException", "null point in template snapshot");
            return empty_result;
        }
        auto& copied = point_buffer[static_cast<std::size_t>(i)];
        copied.x = env->GetIntField(point, point_fields.x);
        copied.y = env->GetIntField(point, point_fields.y);
        copied.distance = env->GetDoubleField(point, point_fields.distance);
        env->DeleteLocalRef(point);
    }
    if (env->ExceptionCheck()) return empty_result;
    if (geometry.width == 0 || geometry.height == 0 || count == 0) return empty_result;

    double result = empty_result;
    bool acquired = false;
    bool copied = false;
    {
        CriticalShorts pinned(env, values);
        if (pinned.values != nullptr) {
            acquired = true;
            copied = pinned.copied != JNI_FALSE;
            // No JNI calls, allocations, logging, waits, or Java callbacks here.
            const auto* storage = reinterpret_cast<const std::int16_t*>(pinned.values);
            result = holes_only
                ? scorer::evaluate_hole(storage, geometry, point_buffer.data(), point_buffer.size(),
                                        x, y, offset_x, offset_y)
                : scorer::evaluate(storage, geometry, point_buffer.data(), point_buffer.size(), weights,
                                   x, y, offset_x, offset_y);
        }
        // RAII releases before diagnostics or any exception is created below.
    }
    if (!acquired) {
        fail(env, "java/lang/OutOfMemoryError", "could not acquire distance storage");
        return empty_result;
    }
    pin_count.fetch_add(1, std::memory_order_relaxed);
    if (copied) copy_count.fetch_add(1, std::memory_order_relaxed);
    return result;
}

jdouble JNICALL native_evaluate(JNIEnv* env, jclass, jshortArray values,
    jint width, jint height, jint stride, jint offset, jobjectArray points,
    jint x, jint y, jint offset_x, jint offset_y, jdouble fore, jdouble back, jdouble hole) {
    return score(env, values, {width, height, stride, offset}, points, x, y, offset_x, offset_y,
                 {fore, back, hole}, false);
}
jdouble JNICALL native_evaluate_hole(JNIEnv* env, jclass, jshortArray values,
    jint width, jint height, jint stride, jint offset, jobjectArray points,
    jint x, jint y, jint offset_x, jint offset_y, jdouble fore, jdouble back, jdouble hole) {
    return score(env, values, {width, height, stride, offset}, points, x, y, offset_x, offset_y,
                 {fore, back, hole}, true);
}
jlongArray JNICALL native_statistics(JNIEnv* env, jclass) {
    // Read-only process-lifetime diagnostics; compare balanced pins/releases only
    // after recognition workers are idle. No reset or test-control interface.
    const jlong values[] = {call_count.load(), pin_count.load(), release_count.load(), copy_count.load()};
    jlongArray result = env->NewLongArray(4);
    if (result != nullptr) env->SetLongArrayRegion(result, 0, 4, values);
    return result;
}
} // namespace

bool OMRRegisterTemplateScorer(JNIEnv* env) {
    jclass scorer_class = env->FindClass("com/notelite/omr/image/NativeTemplateScorer");
    if (scorer_class == nullptr) return false;
    if (point_fields.type == nullptr) {
        jclass local_type = env->FindClass("com/notelite/omr/image/PixelDistance");
        if (local_type == nullptr) { env->DeleteLocalRef(scorer_class); return false; }
        PointFields fields;
        fields.type = static_cast<jclass>(env->NewGlobalRef(local_type));
        env->DeleteLocalRef(local_type);
        if (fields.type == nullptr) { env->DeleteLocalRef(scorer_class); return false; }
        fields.x = env->GetFieldID(fields.type, "x", "I");
        if (fields.x != nullptr) fields.y = env->GetFieldID(fields.type, "y", "I");
        if (fields.y != nullptr) fields.distance = env->GetFieldID(fields.type, "d", "D");
        if (fields.distance == nullptr) {
            env->DeleteGlobalRef(fields.type); env->DeleteLocalRef(scorer_class); return false;
        }
        point_fields = fields;
    }
    constexpr const char* signature = "([SIIII[Lcom/notelite/omr/image/PixelDistance;IIIIDDD)D";
    const JNINativeMethod methods[] = {
        {const_cast<char*>("evaluate0"), const_cast<char*>(signature), reinterpret_cast<void*>(native_evaluate)},
        {const_cast<char*>("evaluateHole0"), const_cast<char*>(signature), reinterpret_cast<void*>(native_evaluate_hole)},
        {const_cast<char*>("statistics0"), const_cast<char*>("()[J"), reinterpret_cast<void*>(native_statistics)}
    };
    if (env->RegisterNatives(scorer_class, methods, 3) != JNI_OK) {
        env->DeleteLocalRef(scorer_class); return false;
    }
    jmethodID enable = env->GetStaticMethodID(scorer_class, "enable", "()V");
    if (enable == nullptr) { env->DeleteLocalRef(scorer_class); return false; }
    env->CallStaticVoidMethod(scorer_class, enable);
    const bool success = !env->ExceptionCheck();
    env->DeleteLocalRef(scorer_class);
    return success;
}
