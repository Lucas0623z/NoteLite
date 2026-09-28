// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
#pragma once

#include <cstddef>
#include <cstdint>
#include <jni.h>

namespace notelite::template_scoring {

// Logical coordinates are relative to the ROI. Storage remains the original
// signed-short array: values[offset + y * stride + x]. All fields must be
// nonnegative, stride >= width, and valid_for() must succeed before evaluation.
struct Geometry {
    std::int32_t width;
    std::int32_t height;
    std::int32_t stride;
    std::int32_t offset;
    bool valid_for(std::size_t storage_count) const noexcept;
};

struct Point {
    std::int32_t x;
    std::int32_t y;
    double distance;
};

struct Weights { double foreground; double background; double hole; };

// Pure, non-owning computation. Geometry is validated, storage and points remain
// alive/read-only, and point_count <= INT32_MAX. No allocation or JNI call occurs.
// Java has already rounded the anchor offsets; integer arithmetic still wraps.
double evaluate(const std::int16_t* storage, Geometry geometry,
                const Point* points, std::size_t point_count, Weights weights,
                std::int32_t x, std::int32_t y,
                std::int32_t offset_x, std::int32_t offset_y) noexcept;
double evaluate_hole(const std::int16_t* storage, Geometry geometry,
                     const Point* points, std::size_t point_count,
                     std::int32_t x, std::int32_t y,
                     std::int32_t offset_x, std::int32_t offset_y) noexcept;
} // namespace notelite::template_scoring

// Call during single-VM startup, before starting recognition workers. The cached
// global class reference and field IDs remain valid for this embedded VM's life.
// A failure preserves the pending Java exception for the host to report.
bool OMRRegisterTemplateScorer(JNIEnv* environment);
