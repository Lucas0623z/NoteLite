/* Copyright (C) 2026 NoteLite contributors. SPDX-License-Identifier: AGPL-3.0-or-later */
package com.notelite.omr.image;

import java.awt.Point;

/** Optional registered native implementation of the original template scoring arithmetic. */
public final class NativeTemplateScorer
{
    private static final PixelDistance[] EMPTY_POINTS = new PixelDistance[0];
    private static volatile boolean enabled;

    private NativeTemplateScorer () {}

    /** Called by the host only after all native methods and point fields are registered. */
    private static void enable ()
    {
        enabled = true;
    }

    public static boolean isEnabled ()
    {
        return enabled;
    }

    /** Read-only counters: native invocations, pins, releases, and copied pins. */
    public static long[] statistics ()
    {
        if (!enabled) throw new IllegalStateException("Native template scorer is not registered");
        return statistics0();
    }

    static short[] supportedValues (DistanceTable distances)
    {
        // A subclass may override distance access; retain its Java behavior.
        return enabled && distances.getClass() == DistanceTable.Short.class
                ? ((DistanceTable.Short) distances).nativeValues() : null;
    }

    static double evaluate (Template template, DistanceTable distances, short[] values, Point ul,
                            double foreground, double background, double hole)
    {
        // The public list is mutable. Take its current order on every call; never cache old points.
        final PixelDistance[] points = template.getKeyPoints().toArray(EMPTY_POINTS);
        final int width = distances.getWidth();
        return evaluate0(values, width, distances.getHeight(), width, 0, points, ul.x, ul.y,
                0, 0, foreground, background, hole);
    }

    static double evaluateHole (Template template, DistanceTable distances, short[] values, Point ul)
    {
        final PixelDistance[] points = template.getKeyPoints().toArray(EMPTY_POINTS);
        final int width = distances.getWidth();
        return evaluateHole0(values, width, distances.getHeight(), width, 0, points, ul.x, ul.y,
                0, 0, 0, 0, 0);
    }

    private static native double evaluate0 (short[] values, int width, int height, int stride,
            int offset, PixelDistance[] points, int x, int y, int offsetX, int offsetY,
            double foreground, double background, double hole);

    private static native double evaluateHole0 (short[] values, int width, int height, int stride,
            int offset, PixelDistance[] points, int x, int y, int offsetX, int offsetY,
            double foreground, double background, double hole);

    private static native long[] statistics0 ();
}
