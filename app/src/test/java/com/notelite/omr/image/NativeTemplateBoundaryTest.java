/* Copyright (C) 2026 NoteLite contributors. SPDX-License-Identifier: AGPL-3.0-or-later */
package com.notelite.omr.image;

import com.notelite.omr.glyph.Shape;
import com.notelite.omr.ui.symbol.MusicFamily;

import org.junit.After;
import org.junit.AfterClass;
import org.junit.BeforeClass;
import org.junit.Test;

import java.awt.Rectangle;
import java.lang.management.ManagementFactory;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Method;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.Assert.assertArrayEquals;
import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertNotNull;
import static org.junit.Assert.assertNull;
import static org.junit.Assert.assertThrows;
import static org.junit.Assert.assertTrue;

/** Small deterministic checks of the actual JNI boundary, run only by nativeTemplateCheckedTest. */
public class NativeTemplateBoundaryTest
{
    private static Method evaluate;
    private static Method evaluateHole;
    private static Path reportDirectory;
    private static final AtomicLong comparisons = new AtomicLong();

    private record Input(short[] values, int width, int height, int stride, int offset,
                         PixelDistance[] points, int x, int y, int offsetX, int offsetY,
                         double foreground, double background, double hole) {}

    @BeforeClass
    public static void requireCheckedProductionLibrary () throws Exception
    {
        assertTrue("This test requires a real checked JNI VM",
                ManagementFactory.getRuntimeMXBean().getInputArguments().contains("-Xcheck:jni"));
        final String reportRoot = System.getProperty("notelite.embeddedTestRoot");
        assertNotNull("The checked task must provide an evidence directory", reportRoot);
        final Path configuredReportDirectory = Path.of(reportRoot).toAbsolutePath();
        // This class has its own test VM. Keep constants/configuration independent
        // of any desktop installation before Template or WellKnowns initializes.
        System.setProperty("notelite.appHome", configuredReportDirectory.resolve("boundary-home").toString());
        final String library = System.getProperty("notelite.nativeTemplateLibrary");
        assertNotNull("nativeTemplateCheckedTest must supply the production library", library);
        final Path libraryPath = Path.of(library).toAbsolutePath();
        assertTrue("The production native library must exist", Files.isRegularFile(libraryPath));
        System.load(libraryPath.toString());
        assertTrue("Production native methods must be registered", NativeTemplateScorer.isEnabled());
        evaluate = nativeMethod("evaluate0");
        evaluateHole = nativeMethod("evaluateHole0");
        assertIdleCounters();
        reportDirectory = configuredReportDirectory;
    }

    @After
    public void everyTestLeavesNoPinnedArray ()
    {
        assertIdleCounters();
    }

    @AfterClass
    public static void writeCheckedEvidence () throws Exception
    {
        // A failed BeforeClass already fails this suite; do not obscure that error.
        if (reportDirectory == null) return;
        assertIdleCounters();
        final long[] stats = NativeTemplateScorer.statistics();
        assertTrue("The suite must execute actual native scores", stats[0] > 0);
        assertTrue("The suite must acquire real primitive storage", stats[1] > 0);
        Files.createDirectories(reportDirectory);
        Files.writeString(reportDirectory.resolve("native-template-boundary-statistics.json"),
                String.format(Locale.ROOT,
                        "{\"checkedJni\":true,\"testCases\":7,\"scorePairs\":%d,"
                        + "\"nativeCalls\":%d,\"pins\":%d,\"releases\":%d,\"copies\":%d}%n",
                        comparisons.get(), stats[0], stats[1], stats[2], stats[3]));
    }

    @Test
    public void roiStrideOffsetSignedValuesAndWrappedCoordinatesMatchJava () throws Exception
    {
        final short[] storage = new short[8 * 7];
        final short[] pattern = {Short.MIN_VALUE, -2, -1, 0, 1, 3, Short.MAX_VALUE};
        for (int i = 0; i < storage.length; i++) storage[i] = pattern[i % pattern.length];
        final short[] unchanged = storage.clone();
        final PixelDistance[] points = {
                new PixelDistance(0, 0, 0), new PixelDistance(1, 0, -0.0),
                new PixelDistance(2, 1, 1), new PixelDistance(1, 2, -1),
                new PixelDistance(-1, 0, -2), new PixelDistance(4, 3, 2),
                new PixelDistance(Integer.MIN_VALUE, 0, 0),
                new PixelDistance(Integer.MAX_VALUE, -1, -1)};
        final int[][] pivots = {{0, 0}, {1, 1}, {-2, -1}, {4, 4},
                {Integer.MIN_VALUE, Integer.MAX_VALUE}, {Integer.MAX_VALUE, Integer.MIN_VALUE}};
        final int[][] anchors = {{0, 0}, {1, -1}, {Integer.MIN_VALUE, Integer.MAX_VALUE}};
        final double[][] weights = {{6, 1, 4}, {.1, .2, .3}, {1e16, 1, 1}, {1e-300, 3e-300, 7e-300}};
        for (int[] pivot : pivots) {
            for (int[] anchor : anchors) {
                for (double[] weight : weights) {
                    assertScores(new Input(storage, 3, 4, 8, 10, points,
                            pivot[0], pivot[1], anchor[0], anchor[1], weight[0], weight[1], weight[2]));
                }
            }
        }
        assertArrayEquals("The JNI scorer only reads the backing array", unchanged, storage);
        storage[10] = 0;
        points[0] = new PixelDistance(0, 0, 1);
        assertScores(new Input(storage, 3, 4, 8, 10, points, 0, 0, 0, 0, 6, 1, 4));
    }

    @Test
    public void emptySupportAndZeroLogicalAreaKeepOriginalSentinels () throws Exception
    {
        final PixelDistance[] point = {new PixelDistance(0, 0, 0)};
        final long[] before = NativeTemplateScorer.statistics();
        for (int[] geometry : new int[][]{{0, 0, 0, 0}, {0, 9, 0, 0}, {9, 0, 9, 0}}) {
            final Input input = new Input(new short[0], geometry[0], geometry[1], geometry[2],
                    geometry[3], point, 0, 0, 0, 0, 6, 1, 4);
            assertScores(input);
            assertBits(Double.MAX_VALUE, invoke(evaluate, input));
            assertBits(0.0, invoke(evaluateHole, input));
        }
        assertScores(new Input(new short[]{1}, 0, 7, 8, 1, point, 0, 0, 0, 0, 6, 1, 4));
        assertScores(new Input(new short[]{1}, 1, 1, 1, 0, new PixelDistance[0], 0, 0, 0, 0, 6, 1, 4));
        final long[] afterEmpty = NativeTemplateScorer.statistics();
        assertEquals("Empty support needs no pin", before[1], afterEmpty[1]);
        assertEquals("Empty support needs no release", before[2], afterEmpty[2]);
        assertScores(new Input(new short[]{-1}, 1, 1, 1, 0, point, 0, 0, 0, 0, 6, 1, 4));
        assertScores(new Input(new short[]{0}, 1, 1, 1, 0, point, 0, 0, 0, 0, 0, 0, 0));
    }

    @Test
    public void illegalAndOverflowingGeometryRejectsBeforePin () throws Exception
    {
        final PixelDistance[] point = {new PixelDistance(0, 0, 0)};
        for (int[] geometry : new int[][]{{-1, 1, 1, 0}, {1, -1, 1, 0}, {1, 1, -1, 0},
                {1, 1, 1, -1}, {2, 1, 1, 0}, {1, 1, 1, 1}, {2, 2, 2, 0},
                {0, 0, 0, 2}, {1, Integer.MAX_VALUE, Integer.MAX_VALUE, 0},
                {Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE, Integer.MAX_VALUE}}) {
            assertRejected(new Input(new short[1], geometry[0], geometry[1], geometry[2],
                    geometry[3], point, 0, 0, 0, 0, 6, 1, 4), IllegalArgumentException.class);
        }
        assertRejected(new Input(new short[0], 1, 1, 1, 0, point, 0, 0, 0, 0, 6, 1, 4),
                IllegalArgumentException.class);
    }

    @Test
    public void nullStorageSnapshotsAndElementsRejectBeforePin () throws Exception
    {
        final PixelDistance[] point = {new PixelDistance(0, 0, 0)};
        assertRejected(new Input(null, 1, 1, 1, 0, point, 0, 0, 0, 0, 6, 1, 4),
                NullPointerException.class);
        assertRejected(new Input(new short[1], 1, 1, 1, 0, null, 0, 0, 0, 0, 6, 1, 4),
                NullPointerException.class);
        assertRejected(new Input(new short[1], 1, 1, 1, 0,
                new PixelDistance[]{point[0], null}, 0, 0, 0, 0, 6, 1, 4), NullPointerException.class);
    }

    @Test
    public void validCallsRecoverAfterRejectedPartialSnapshots () throws Exception
    {
        for (int i = 0; i < 64; i++) {
            final PixelDistance[] points = {new PixelDistance(0, 0, i % 3 - 1),
                    new PixelDistance(1, 0, 0), new PixelDistance(0, 1, -1)};
            assertRejected(new Input(new short[4], 2, 2, 2, 0,
                    new PixelDistance[]{points[0], null, points[2]}, 0, 0, 0, 0, 6, 1, 4),
                    NullPointerException.class);
            final long[] before = NativeTemplateScorer.statistics();
            assertScores(new Input(new short[]{0, 1, -2, -1}, 2, 2, 2, 0,
                    points, 0, 0, 0, 0, .1, .2, .3));
            final long[] after = NativeTemplateScorer.statistics();
            assertEquals(2, after[1] - before[1]);
            assertEquals(2, after[2] - before[2]);
        }
    }

    @Test
    public void unsupportedDistanceTablesKeepJavaSemanticsAndNativeRemainsUsable () throws Exception
    {
        final Template template = new Template(Shape.NOTEHEAD_BLACK, MusicFamily.Bravura, 20,
                1, 1, List.of(new PixelDistance(0, 0, 0)), new Rectangle(0, 0, 1, 1));
        final DistanceTable integer = new DistanceTable.Integer(1, 1, 3);
        integer.setValue(0, 65536); // Must remain nonzero; narrowing to short would silently change it.
        final DistanceTable.Short parent = new DistanceTable.Short(4, 3, 3);
        parent.setValue(2, 1, 3);
        final DistanceTable view = parent.getView(new Rectangle(2, 1, 1, 1));
        final DistanceTable overridden = new DistanceTable.Short(1, 1, 3) {
            @Override public int getValue (int x, int y) { return 1; }
        };
        final long[] before = NativeTemplateScorer.statistics();
        for (DistanceTable table : List.of(integer, view, overridden)) {
            assertNull("Unsupported access must not expose a misleading backing array",
                    NativeTemplateScorer.supportedValues(table));
            assertBits(1.0, template.evaluate(0, 0, null, table));
            assertBits(0.0, template.evaluateHole(0, 0, null, table));
        }
        assertEquals("Unsupported tables retain Java execution", before[0], NativeTemplateScorer.statistics()[0]);
        assertScores(healthyInput(0));
    }

    @Test(timeout = 30000)
    public void concurrentCallsAndGcRequestsLeaveBalancedPins () throws Exception
    {
        final long[] before = NativeTemplateScorer.statistics();
        final CountDownLatch start = new CountDownLatch(1);
        final ExecutorService pool = Executors.newFixedThreadPool(3);
        final List<Future<Void>> tasks = new ArrayList<>();
        try {
            for (int worker = 0; worker < 2; worker++) {
                final int lane = worker;
                tasks.add(pool.submit(() -> {
                    start.await();
                    for (int i = 0; i < 400; i++) assertScores(healthyInput(i + 17 * lane));
                    return null;
                }));
            }
            tasks.add(pool.submit(() -> {
                start.await();
                for (int i = 0; i < 16; i++) {
                    final byte[] pressure = new byte[4096];
                    Arrays.fill(pressure, (byte) i);
                    System.gc(); // Requested from Java, never while this thread owns a critical array.
                    assertEquals((byte) i, pressure[pressure.length - 1]);
                }
                return null;
            }));
            start.countDown();
            for (Future<Void> task : tasks) task.get(20, TimeUnit.SECONDS);
        } finally {
            start.countDown();
            pool.shutdownNow();
            assertTrue("Workers must be idle before checking release counters",
                    pool.awaitTermination(5, TimeUnit.SECONDS));
        }
        final long[] after = NativeTemplateScorer.statistics();
        assertEquals(1600, after[0] - before[0]);
        assertEquals(1600, after[1] - before[1]);
        assertEquals(1600, after[2] - before[2]);
    }

    private static Input healthyInput (int seed)
    {
        final short[] values = new short[8 * 6];
        for (int i = 0; i < values.length; i++) values[i] = (short) ((i + seed) % 7 - 2);
        final PixelDistance[] points = new PixelDistance[32];
        for (int i = 0; i < points.length; i++) {
            points[i] = new PixelDistance(i % 6 - 1, i / 6 - 1, (i + seed) % 3 - 1);
        }
        return new Input(values, 5, 4, 8, 9, points, seed % 3, seed % 2, 1, -1, .1, .2, .3);
    }

    private static Method nativeMethod (String name) throws Exception
    {
        final Method method = NativeTemplateScorer.class.getDeclaredMethod(name,
                short[].class, int.class, int.class, int.class, int.class, PixelDistance[].class,
                int.class, int.class, int.class, int.class, double.class, double.class, double.class);
        method.setAccessible(true);
        return method;
    }

    private static double invoke (Method method, Input input) throws Exception
    {
        try {
            return (Double) method.invoke(null, input.values, input.width, input.height, input.stride,
                    input.offset, input.points, input.x, input.y, input.offsetX, input.offsetY,
                    input.foreground, input.background, input.hole);
        } catch (InvocationTargetException exception) {
            if (exception.getCause() instanceof RuntimeException cause) throw cause;
            if (exception.getCause() instanceof Error cause) throw cause;
            throw new AssertionError(exception.getCause());
        }
    }

    private static void assertRejected (Input input, Class<? extends Throwable> exception) throws Exception
    {
        for (Method method : List.of(evaluate, evaluateHole)) {
            final long[] before = NativeTemplateScorer.statistics();
            assertThrows(exception, () -> invoke(method, input));
            final long[] after = NativeTemplateScorer.statistics();
            assertEquals("The request reached the actual native method", before[0] + 1, after[0]);
            assertEquals("Rejected input never pins", before[1], after[1]);
            assertEquals("Rejected input never releases an unacquired array", before[2], after[2]);
        }
    }

    private static void assertScores (Input input) throws Exception
    {
        final double[] expected = originalScores(input);
        assertBits(expected[0], invoke(evaluate, input));
        assertBits(expected[1], invoke(evaluateHole, input));
        comparisons.incrementAndGet();
    }

    /** Original Java scalar arithmetic, on small deterministic storage only. */
    private static double[] originalScores (Input input)
    {
        final int left = input.x - input.offsetX;
        final int top = input.y - input.offsetY;
        double total = 0, weights = 0;
        int expectedHoles = 0, actualHoles = 0;
        for (PixelDistance point : input.points) {
            final int x = left + point.x;
            final int y = top + point.y;
            if (x < 0 || x >= input.width || y < 0 || y >= input.height) continue;
            final int actual = input.values[input.offset + y * input.stride + x];
            if (actual == -1) continue;
            final double weight = point.d == 0 ? input.foreground
                    : point.d > 0 ? input.background : input.hole;
            final double expectedDistance = point.d == 0 ? 0 : 1;
            final double actualDistance = actual == 0 ? 0 : 1;
            total += weight * Math.abs(actualDistance - expectedDistance);
            weights += weight;
            if (point.d < 0) {
                expectedHoles++;
                if (actual != 0) actualHoles++;
            }
        }
        return new double[]{weights == 0 ? Double.MAX_VALUE : total / weights,
                expectedHoles == 0 ? 0.0 : (double) actualHoles / expectedHoles};
    }

    private static void assertBits (double expected, double actual)
    {
        assertEquals("Original binary64 score bits", Double.doubleToRawLongBits(expected),
                Double.doubleToRawLongBits(actual));
    }

    private static void assertIdleCounters ()
    {
        final long[] stats = NativeTemplateScorer.statistics();
        assertEquals(4, stats.length);
        assertTrue(stats[0] >= stats[1]);
        assertEquals("Every acquired array is released after workers are idle", stats[1], stats[2]);
        assertTrue("The VM may copy, but copied acquisitions cannot exceed all acquisitions",
                stats[3] >= 0 && stats[3] <= stats[1]);
    }
}
