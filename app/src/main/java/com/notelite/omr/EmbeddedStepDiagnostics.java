// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 NoteLite contributors.
package com.notelite.omr;

import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.lang.management.ThreadMXBean;
import java.lang.management.GarbageCollectorMXBean;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.Comparator;
import java.util.Map;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicBoolean;

/** Bounded diagnostic evidence for real embedded recognition; never substitutes recognition results. */
public final class EmbeddedStepDiagnostics
{
    private static volatile Job active;

    private EmbeddedStepDiagnostics () { }

    static void beginJob (Path output)
    {
        active = new Job(output);
    }

    static void endJob ()
    {
        final Job job = active;
        active = null;
        if (job != null) job.sampler.shutdown();
    }

    public static Step beginStep (String sheet, String name)
    {
        final Job job = active;
        return job == null ? null : new Step(job, sheet, name);
    }

    static void dumpThreads (String reason)
    {
        final Job job = active;
        if (job != null) job.dumpThreads(reason);
    }

    private static String quote (String value)
    {
        final StringBuilder result = new StringBuilder("\"");
        for (int index = 0; index < value.length(); index++) {
            final char c = value.charAt(index);
            if (c == '"' || c == '\\') result.append('\\').append(c);
            else if (c < 32) result.append(String.format("\\u%04x", (int) c));
            else result.append(c);
        }
        return result.append('"').toString();
    }

    private static final class Job
    {
        final Path output;
        final long started = System.nanoTime();
        final ThreadMXBean cpu;
        final String cpuStatus;
        final List<GarbageCollectorMXBean> collectors;
        final ExecutorService sampler = Executors.newSingleThreadExecutor(work -> {
            final Thread thread = new Thread(work, "embedded-diagnostic-sampler");
            thread.setDaemon(true);
            return thread;
        });
        final AtomicBoolean samplePending = new AtomicBoolean();
        final AtomicBoolean dumpPending = new AtomicBoolean();

        Job (Path output)
        {
            this.output = output;
            ThreadMXBean available = null;
            String status;
            try {
                final ThreadMXBean bean = ManagementFactory.getThreadMXBean();
                if (!bean.isThreadCpuTimeSupported()) status = "unsupported";
                else {
                    if (!bean.isThreadCpuTimeEnabled()) bean.setThreadCpuTimeEnabled(true);
                    available = bean;
                    status = "enabled";
                }
            } catch (RuntimeException | LinkageError ex) {
                status = "unavailable: " + ex.getClass().getSimpleName() + ": " + ex.getMessage();
            }
            cpu = available;
            cpuStatus = status;
            List<GarbageCollectorMXBean> gc;
            try { gc = ManagementFactory.getGarbageCollectorMXBeans(); }
            catch (RuntimeException | LinkageError ex) { gc = List.of(); }
            collectors = gc;
            write("{\"event\":\"job-start\",\"timestamp\":" + quote(Instant.now().toString())
                    + ",\"cpuTimeStatus\":" + quote(cpuStatus)
                    + ",\"stepTimeoutSeconds\":" + Main.getSheetStepTimeOut()
                    + ",\"totalJobTimeoutSeconds\":"
                    + (Boolean.getBoolean("notelite.omr.jniHost") ? "900" : "null") + "}");
        }

        long gcValue (boolean time)
        {
            if (collectors.isEmpty()) return -1;
            long total = 0;
            try {
                for (GarbageCollectorMXBean collector : collectors) {
                    final long value = time ? collector.getCollectionTime() : collector.getCollectionCount();
                    if (value < 0) return -1;
                    total += value;
                }
                return total;
            } catch (RuntimeException | LinkageError ex) { return -1; }
        }

        void enqueue (AtomicBoolean pending, Runnable operation)
        {
            if (!pending.compareAndSet(false, true)) return;
            try {
                sampler.execute(() -> {
                    try { operation.run(); }
                    finally { pending.set(false); }
                });
            } catch (RejectedExecutionException ex) { pending.set(false); }
        }

        long cpuNanos (Thread thread)
        {
            try {
                return cpu == null ? -1 : cpu.getThreadCpuTime(thread.threadId());
            } catch (RuntimeException | LinkageError ex) {
                return -1;
            }
        }

        synchronized void write (String json)
        {
            System.err.println("EMBEDDED_OMR_TIMING " + json);
            try {
                Files.writeString(output.resolve("embedded-step-timing.jsonl"), json + "\n",
                        StandardOpenOption.CREATE, StandardOpenOption.APPEND);
            } catch (IOException ex) {
                System.err.println("EMBEDDED_OMR_DIAGNOSTIC_WRITE_FAILED " + ex);
            }
        }

        void dumpThreads (String reason)
        {
            // Thread stack retrieval can wait for a VM safepoint. The deadline
            // and cancellation paths must never wait for that retrieval.
            enqueue(dumpPending, () -> captureThreads(reason));
        }

        void captureThreads (String reason)
        {
            final StringBuilder dump = new StringBuilder("reason=" + reason + " timestamp="
                    + Instant.now() + " cpuTimeStatus=" + cpuStatus + "\n");
            try {
                final var threads = Thread.getAllStackTraces().entrySet().stream()
                        .sorted(Comparator.comparingLong(entry -> entry.getKey().threadId()))
                        .limit(128).toList();
                for (Map.Entry<Thread, StackTraceElement[]> entry : threads) {
                    final Thread thread = entry.getKey();
                    final long cpuTime = cpuNanos(thread);
                    dump.append('\n').append(thread.getName()).append(" id=").append(thread.threadId())
                            .append(" state=").append(thread.getState()).append(" cpuNanos=")
                            .append(cpuTime < 0 ? "unavailable" : Long.toString(cpuTime)).append('\n');
                    final StackTraceElement[] stack = entry.getValue();
                    for (int index = 0; index < Math.min(stack.length, 64); index++) {
                        dump.append("  at ").append(stack[index]).append('\n');
                    }
                }
                final String name = "embedded-threads-" + reason.replaceAll("[^A-Za-z0-9_-]", "_")
                        + "-" + (System.nanoTime() - started) / 1_000_000 + ".txt";
                Files.writeString(output.resolve(name), dump);
                System.err.println("EMBEDDED_OMR_THREAD_DUMP " + name + "\n" + dump);
            } catch (IOException | RuntimeException | LinkageError ex) {
                System.err.println("EMBEDDED_OMR_THREAD_DUMP_UNAVAILABLE " + ex);
            }
        }
    }

    public static final class Step
    {
        private final Job job;
        private final String sheet;
        private final String name;
        private final Thread worker = Thread.currentThread();
        private final long started = System.nanoTime();
        private final long initialCPU;
        private final long initialGCCount;
        private final long initialGCTime;

        private Step (Job job, String sheet, String name)
        {
            this.job = job;
            this.sheet = sheet;
            this.name = name;
            initialCPU = job.cpuNanos(worker);
            initialGCCount = job.gcValue(false);
            initialGCTime = job.gcValue(true);
            sample("start", false);
        }

        public void sample (String event, boolean stack)
        {
            if (stack) {
                capture(event, false);
                job.enqueue(job.samplePending, () -> capture(event + "-stack", true));
            } else capture(event, false);
        }

        private static String delta (long initial, long current)
        {
            return initial < 0 || current < initial ? "null" : Long.toString(current - initial);
        }

        private void capture (String event, boolean stack)
        {
            final long currentCPU = job.cpuNanos(worker);
            final String cpuMilliseconds = initialCPU < 0 || currentCPU < initialCPU
                    ? "null" : Long.toString((currentCPU - initialCPU) / 1_000_000);
            final StringBuilder json = new StringBuilder("{\"event\":" + quote(event)
                    + ",\"timestamp\":" + quote(Instant.now().toString())
                    + ",\"sheet\":" + quote(sheet) + ",\"step\":" + quote(name)
                    + ",\"wallMilliseconds\":" + (System.nanoTime() - started) / 1_000_000
                    + ",\"workerThread\":" + quote(worker.getName())
                    + ",\"workerState\":" + quote(worker.getState().name())
                    + ",\"workerCPUMilliseconds\":" + cpuMilliseconds
                    + ",\"processGCCollections\":" + delta(initialGCCount, job.gcValue(false))
                    + ",\"processGCMilliseconds\":" + delta(initialGCTime, job.gcValue(true))
                    + ",\"cpuTimeStatus\":" + quote(job.cpuStatus));
            if (stack) {
                json.append(",\"stack\":[");
                final StackTraceElement[] frames = worker.getStackTrace();
                for (int index = 0; index < Math.min(frames.length, 16); index++) {
                    if (index > 0) json.append(',');
                    json.append(quote(frames[index].toString()));
                }
                json.append(']');
            }
            job.write(json.append('}').toString());
        }

        public void timedOut ()
        {
            sample("timeout", false);
            job.dumpThreads(name + "-timeout");
        }
    }
}
