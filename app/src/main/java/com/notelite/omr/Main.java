//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                            M a i n                                             //
//                                                                                                //
//------------------------------------------------------------------------------------------------//
// <editor-fold defaultstate="collapsed" desc="hdr">
//
//  Copyright © NoteLite 2026. All rights reserved.
//
//  This program is free software: you can redistribute it and/or modify it under the terms of the
//  GNU Affero General Public License as published by the Free Software Foundation, either version
//  3 of the License, or (at your option) any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
//  without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
//  See the GNU Affero General Public License for more details.
//
//  You should have received a copy of the GNU Affero General Public License along with this
//  program.  If not, see <http://www.gnu.org/licenses/>.
//------------------------------------------------------------------------------------------------//
// </editor-fold>
package com.notelite.omr;

import com.notelite.omr.CLI.CliTask;
import com.notelite.omr.classifier.SampleRepository;
import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantManager;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.log.LogUtil;
import com.notelite.omr.sheet.BookManager;
import com.notelite.omr.text.tesseract.Languages;
import com.notelite.omr.text.tesseract.TesseractOCR;
import com.notelite.omr.ui.MainGui;
import com.notelite.omr.ui.symbol.MusicFont;
import com.notelite.omr.ui.util.UIUtil;
import com.notelite.omr.ui.util.VectorIcons;
import com.notelite.omr.util.OmrExecutors;

import org.jdesktop.application.Application;

import org.kohsuke.args4j.CmdLineException;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.TreeSet;
import java.util.Set;
import java.nio.file.Files;
import java.nio.file.Path;
import java.io.IOException;
import java.util.function.BooleanSupplier;
import com.notelite.omr.step.ProcessingCancellationException;
import java.util.concurrent.Callable;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

/**
 * Class <code>Main</code> is the main class for OMR application.
 * <p>
 * It deals with the main routine and its command line parameters.
 * It launches the User Interface, unless batch mode is selected.
 *
 * @see CLI
 * @author NoteLite Contributors
 */
public class Main
{
    //~ Static fields/initializers -----------------------------------------------------------------

    static {
        // We need class WellKnowns to be elaborated before anything else
        WellKnowns.ensureLoaded();
    }

    private static final Logger logger = LoggerFactory.getLogger(Main.class);

    private static final Constants constants = new Constants();

    /** CLI parameters. */
    private static volatile CLI cli;

    private static boolean embeddedLogInitialized;

    private static EmbeddedPreviousState embeddedPendingRestore;

    private record EmbeddedPreviousState(CLI cli, Locale locale, boolean parallelism) { }

    /** A batch result is returned to an embedded host; it never terminates that host's JVM. */
    public record BatchResult(BatchStatus status, int completedTasks, List<String> errors)
    {
        public BatchResult {
            errors = List.copyOf(errors);
        }
    }

    public enum BatchStatus { SUCCESS, FAILED, CANCELLED, TIMED_OUT }

    //~ Constructors -------------------------------------------------------------------------------

    private Main ()
    {
    }

    //~ Static Methods -----------------------------------------------------------------------------

    //-------------//
    // checkLocale //
    //-------------//
    private static void checkLocale ()
    {
        final String localeStr = constants.locale.getValue().trim();

        Locale locale = getLocale(localeStr);

        if (locale != null) {
            Locale.setDefault(locale);
            logger.debug("Locale set to {}", locale);
        }
    }

    //--------//
    // getCli //
    //--------//
    /**
     * Points to the command line interface parameters
     *
     * @return CLI instance
     */
    public static CLI getCli ()
    {
        return cli;
    }

    //-----------//
    // getLocale //
    //-----------//
    private static Locale getLocale (String localeStr)
    {
        if (!localeStr.isEmpty()) {
            for (Locale locale : Locale.getAvailableLocales()) {
                if (locale.toString().equalsIgnoreCase(localeStr)) {
                    return locale;
                }
            }

            logger.warn("Not supported locale {}", localeStr);
        }

        return null;
    }

    //---------------------//
    // getSheetStepTimeOut //
    //---------------------//
    /**
     * Report the timeout value for any step on a sheet.
     *
     * @return the timeout value (in seconds)
     */
    public static int getSheetStepTimeOut ()
    {
        if (usesNativeEmbeddedBudgets()) return 300;
        return constants.sheetStepTimeOut.getValue();
    }

    private static boolean usesNativeEmbeddedBudgets ()
    {
        return WellKnowns.APP_HOME != null && Boolean.getBoolean("notelite.omr.jniHost");
    }

    //---------------------//
    // getSupportedLocales //
    //---------------------//
    public static List<Locale> getSupportedLocales ()
    {
        final List<Locale> locales = new ArrayList<>();
        final String str = constants.supportedLocales.getValue();
        final String[] tokens = str.split("\\s*,\\s*");

        for (String token : tokens) {
            String trimmedToken = token.trim();

            if (!trimmedToken.isEmpty()) {
                Locale locale = getLocale(trimmedToken);

                if (locale != null) {
                    locales.add(locale);
                }
            }
        }

        return locales;
    }

    //------------//
    // initialize //
    //------------//
    private static void initialize ()
    {
        // (re) Open the executor services
        OmrExecutors.restart();
    }

    //----------//
    // logTasks //
    //----------//
    private static void logTasks (List<CliTask> tasks,
                                  boolean inParallel)
    {
        StringBuilder sb = new StringBuilder();
        sb.append("Submitting ").append(tasks.size()).append(" task(s) in ");
        sb.append(inParallel ? "parallel:" : "sequence:");

        for (Callable task : tasks) {
            sb.append("\n    ").append(task);
        }

        logger.info(sb.toString());
    }

    //------//
    // main //
    //------//
    /**
     * Specific starting method for the application.
     *
     * @param args command line parameters
     * @see com.notelite.omr.CLI the possible command line parameters
     */
    public static void main (String[] args)
    {
        // Log files
        LogUtil.addFileAppender();

        // Process CLI parameters
        processCli(args);

        if (!cli.isBatchMode()) {
            // Log all events to LogPane
            LogUtil.addGuiAppender();
        }

        // Locale to be used in the whole application?
        checkLocale();

        // Help?
        if (cli.isHelpMode()) {
            cli.printUsage();

            return;
        }

        // Version?
        if (cli.isVersionMode()) {
            showEnvironment();
            return;
        }

        // Initialize tool parameters
        initialize();

        // Engine
        OMR.engine = BookManager.getInstance();

        if (!cli.isBatchMode()) {
            logger.debug("Running in interactive mode");

            // Select proper fonts names and sizes
            UIUtil.adjustDefaultFonts();

            // Substitute scalable SVG icons for the legacy Crystal PNG icons
            VectorIcons.install();

            logger.debug("Main. Launching MainGui");
            Application.launch(MainGui.class, args);
        } else {
            ///System.setProperty("java.awt.headless", "true"); //TODO: Useful?
            logger.info("Running in batch mode");

            // Perhaps time to check for a new release?
            // Fix for issue #562: Disable this check when running in batch mode.
            ///Versions.considerPolling();

            // Check OCR languages
            Languages.getInstance().checkSupport();

            // Check MusicFont is loaded
            MusicFont.checkMusicFont();

            // Run the required tasks, if any (and remember if at least one task failed)
            final boolean failure = runBatchTasks();

            // At this point all tasks have completed (except timeout...)
            // So shutdown gracefully the executors
            final boolean timeout = !OmrExecutors.shutdown();

            // Save global sample repository if modified
            if (SampleRepository.hasInstance()) {
                SampleRepository repository = SampleRepository.getGlobalInstance(false);

                if (repository.isModified()) {
                    repository.storeRepository();
                }
            }

            // Store latest constant values on disk?
            if (constants.persistBatchCliConstants.getValue()) {
                ConstantManager.getInstance().storeResource();
            }

            // Force JVM exit?
            if (failure || timeout) {
                String msg = "Exit forced.";
                int status = 0;

                if (failure) {
                    status += 1;
                    msg += " Failure";
                }

                if (timeout) {
                    status += 2;
                    msg += " Timeout";
                }

                logger.warn(msg);
                System.exit(status);
            }
        }
    }

    /**
     * Run real CLI processing within an existing JVM. Use {@link EmbeddedOmrEngine#open(Path)}
     * first so headless mode and sandbox paths are installed before AWT/WellKnowns initialize.
     * This method accepts only batch recognition options; no arbitrary classes or @files.
     * Desktop {@link #main(String[])} retains its existing exit behavior.
     */
    public static synchronized BatchResult runEmbeddedBatch (String[] args)
    {
        return runEmbeddedBatch(args, () -> false);
    }

    static synchronized BatchResult runEmbeddedBatch (String[] args, BooleanSupplier cancelled)
    {
        if (!Boolean.getBoolean("java.awt.headless") || WellKnowns.APP_HOME == null) {
            throw new IllegalStateException("Initialize EmbeddedOmrEngine before invoking embedded OMR");
        }
        if (OMR.gui != null) {
            throw new IllegalStateException("Embedded processing cannot share an interactive OMR session");
        }
        if (cancelled.getAsBoolean() || Thread.currentThread().isInterrupted()) {
            return new BatchResult(BatchStatus.CANCELLED, 0, List.of());
        }
        validateEmbeddedArguments(args);
        final CLI parsed = new CLI(WellKnowns.TOOL_DISPLAY_NAME);
        final CLI.Parameters parameters;
        try {
            parameters = parsed.parseParameters(args.clone());
        } catch (CmdLineException ex) {
            throw new IllegalArgumentException("Invalid embedded OMR arguments: " + ex.getMessage(), ex);
        }
        if (!parameters.batchMode) {
            throw new IllegalArgumentException("Embedded OMR requires -batch");
        }
        if (parameters.helpMode || parameters.versionMode) {
            return new BatchResult(BatchStatus.SUCCESS, 0, List.of());
        }
        try {
            validateEmbeddedPaths(parameters);
        } catch (IOException ex) {
            throw new IllegalArgumentException("Invalid embedded OMR path: " + ex.getMessage(), ex);
        }

        OmrExecutors.restartForEmbedded();
        // A timed-out job keeps its context until all of its workers have actually stopped.
        if (embeddedPendingRestore != null) {
            cli = embeddedPendingRestore.cli();
            Locale.setDefault(embeddedPendingRestore.locale());
            OmrExecutors.defaultParallelism.setSpecific(embeddedPendingRestore.parallelism());
            embeddedPendingRestore = null;
        }
        // No CLI values from earlier completed jobs survive in Main.getCli().
        final CLI previousCli = cli;
        final Locale previousLocale = Locale.getDefault();
        final boolean previousParallelism = OmrExecutors.defaultParallelism.getValue();
        final List<String> errors = new ArrayList<>();
        BatchStatus status = BatchStatus.SUCCESS;
        int completed = 0;
        cli = parsed;
        final ScopedCancellation jobCancellation = new ScopedCancellation(cancelled);
        EmbeddedStepDiagnostics.beginJob(parameters.outputFolder);
        try {
            final BatchResult work = usesNativeEmbeddedBudgets()
                    ? runWithEmbeddedDeadline(() -> executeEmbeddedTasks(parsed, jobCancellation), 900_000)
                    : executeEmbeddedTasks(parsed, jobCancellation);
            status = work.status();
            completed = work.completedTasks();
            errors.addAll(work.errors());
        } catch (TimeoutException ex) {
            status = BatchStatus.TIMED_OUT;
            errors.add("Embedded recognition exceeded its 900 second total job budget");
            logger.warn("Embedded OMR total job deadline exceeded", ex);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            status = BatchStatus.CANCELLED;
            errors.add("Embedded recognition was interrupted");
        } catch (Exception | LinkageError ex) {
            status = BatchStatus.FAILED;
            errors.add(ex.getClass().getSimpleName() + ": " + ex.getMessage());
            logger.warn("Embedded OMR initialization failed", ex);
        } finally {
            // A deadline may leave a worker alive after the JNI caller releases
            // its token. Close the short atomic callback before returning.
            jobCancellation.close();
            if (!OmrExecutors.shutdownForEmbedded(status != BatchStatus.SUCCESS, 30_000)) {
                EmbeddedStepDiagnostics.dumpThreads("workers-did-not-terminate");
                status = BatchStatus.TIMED_OUT;
                errors.add("OMR workers did not terminate; a new job is refused until they finish");
                embeddedPendingRestore = new EmbeddedPreviousState(
                        previousCli, previousLocale, previousParallelism);
            } else {
                OmrExecutors.defaultParallelism.setSpecific(previousParallelism);
                Locale.setDefault(previousLocale);
                cli = previousCli;
            }
            EmbeddedStepDiagnostics.endJob();
        }
        return new BatchResult(status, completed, errors);
    }

    static final class ScopedCancellation implements BooleanSupplier, AutoCloseable
    {
        private final BooleanSupplier external;
        private boolean closed;

        ScopedCancellation (BooleanSupplier external) { this.external = external; }

        @Override public synchronized boolean getAsBoolean ()
        {
            return closed || external.getAsBoolean();
        }

        @Override public synchronized void close () { closed = true; }
    }

    /** The tracked pool retains timed-out workers so later jobs cannot overlap them. */
    static <T> T runWithEmbeddedDeadline (Callable<T> work, long timeoutMillis) throws Exception
    {
        if (timeoutMillis <= 0 || timeoutMillis > 900_000) {
            throw new IllegalArgumentException("Embedded job budget must be within 1..900000 milliseconds");
        }
        final Future<T> future = OmrExecutors.getCachedLowExecutor().submit(work);
        try {
            return future.get(timeoutMillis, TimeUnit.MILLISECONDS);
        } catch (TimeoutException ex) {
            EmbeddedStepDiagnostics.dumpThreads("job-deadline");
            throw ex;
        } catch (ExecutionException ex) {
            if (ex.getCause() instanceof Exception cause) throw cause;
            if (ex.getCause() instanceof Error cause) throw cause;
            throw ex;
        } finally {
            if (!future.isDone()) future.cancel(true);
        }
    }

    private static BatchResult executeEmbeddedTasks (CLI parsed, BooleanSupplier cancelled)
    {
        final List<String> errors = new ArrayList<>();
        BatchStatus status = BatchStatus.SUCCESS;
        int completed = 0;
        try {
            if (!embeddedLogInitialized) {
                LogUtil.addFileAppender();
                embeddedLogInitialized = true;
            }
            checkLocale();
            // Bound concurrency on mobile; jobs and sheets execute in a stable sequence.
            OmrExecutors.defaultParallelism.setSpecific(false);
            OMR.engine = BookManager.getInstance();
            Languages.getInstance().checkSupport();
            MusicFont.checkMusicFont();
            final List<CliTask> tasks = parsed.getCliTasks();
            for (CliTask task : tasks) {
                if (cancelled.getAsBoolean() || Thread.currentThread().isInterrupted()) {
                    status = BatchStatus.CANCELLED;
                    break;
                }
                try {
                    task.call();
                    completed++;
                } catch (Exception ex) {
                    status = ex instanceof ProcessingCancellationException
                            || ex instanceof InterruptedException
                            || Thread.currentThread().isInterrupted()
                            ? BatchStatus.CANCELLED : BatchStatus.FAILED;
                    errors.add(ex.getClass().getSimpleName() + ": " + ex.getMessage());
                    logger.warn("Embedded OMR task failed", ex);
                    break;
                }
            }
            if (cancelled.getAsBoolean() || Thread.currentThread().isInterrupted()) {
                status = BatchStatus.CANCELLED;
            }
        } catch (RuntimeException | LinkageError ex) {
            status = BatchStatus.FAILED;
            errors.add(ex.getClass().getSimpleName() + ": " + ex.getMessage());
            logger.warn("Embedded OMR initialization failed", ex);
        }
        return new BatchResult(status, completed, errors);
    }

    private static void validateEmbeddedArguments (String[] args)
    {
        if (args == null) {
            throw new IllegalArgumentException("Arguments must not be null");
        }
        final Set<String> options = Set.of("-batch", "-transcribe", "-export", "-export-midi",
                "-output", "-step", "-save", "-swap", "-force", "-help", "-version", "--");
        boolean literal = false;
        for (String argument : args) {
            if (argument == null || argument.startsWith("@")) {
                throw new IllegalArgumentException("Null arguments and @files are not supported");
            }
            if (!literal && argument.startsWith("-") && !options.contains(argument)) {
                throw new IllegalArgumentException("Unsupported embedded option: " + argument);
            }
            if (argument.equals("--")) {
                literal = true;
            }
        }
    }

    private static void validateEmbeddedPaths (CLI.Parameters parameters) throws IOException
    {
        final Path root = WellKnowns.APP_HOME.toRealPath();
        if (parameters.arguments.size() != 1 || parameters.outputFolder == null) {
            throw new IllegalArgumentException("Embedded OMR requires one input and an output directory");
        }
        final Path input = parameters.arguments.get(0).toRealPath();
        final Path output = parameters.outputFolder.toRealPath();
        if (!input.startsWith(root) || !output.startsWith(root)
                || !Files.isRegularFile(input) || !Files.isDirectory(output)) {
            throw new IllegalArgumentException("Embedded input and output must stay inside appHome");
        }
        final String name = input.getFileName().toString().toLowerCase(Locale.ROOT);
        if (!(name.endsWith(".png") || name.endsWith(".jpg") || name.endsWith(".jpeg")
                || name.endsWith(".tif") || name.endsWith(".tiff") || name.endsWith(".bmp")
                || name.endsWith(".gif") || name.endsWith(".pdf"))) {
            throw new IllegalArgumentException("Embedded input must be an image or PDF, not a saved book");
        }
    }

    //------------//
    // processCli //
    //------------//
    private static void processCli (String[] args)
    {
        try {
            // First get the provided parameters if any
            cli = new CLI(WellKnowns.TOOL_DISPLAY_NAME);
            cli.parseParameters(args);
        } catch (CmdLineException ex) {
            logger.warn("Error in command line: {}", ex.getLocalizedMessage(), ex);
            logger.warn("Exiting ...");

            // Stop the JVM, with failure status (1)
            Runtime.getRuntime().exit(1);
        }
    }

    //---------------//
    // runBatchTasks //
    //---------------//
    private static boolean runBatchTasks ()
    {
        boolean failure = false;
        final List<CliTask> tasks = cli.getCliTasks();

        if (!tasks.isEmpty()) {
            // Run all tasks in parallel? (or one task at a time)
            if (constants.runBatchTasksInParallel.isSet()) {
                try {
                    logTasks(tasks, true);

                    List<Future<Void>> futures = OmrExecutors.getCachedLowExecutor().invokeAll(
                            tasks);
                    logger.info("Checking {} task(s)", tasks.size());

                    // Check for time-out
                    for (Future<Void> future : futures) {
                        try {
                            future.get();
                        } catch (InterruptedException | ExecutionException ex) {
                            CliTask task = tasks.get(futures.indexOf(future));
                            final String radix = task.getRadix();

                            logger.warn("Future exception on {}, {}", radix, ex.toString(), ex);
                            failure = true;
                        }
                    }
                } catch (InterruptedException ex) {
                    logger.warn("Error in processing tasks", ex);
                    failure = true;
                }
            } else {
                logTasks(tasks, false);

                for (CliTask task : tasks) {
                    try {
                        task.call();
                    } catch (Exception ex) {
                        final String radix = task.getRadix();
                        logger.warn("Exception on {}, {}", radix, ex.toString(), ex);
                        failure = true;
                    }
                }
            }
        }

        return failure;
    }

    //-----------//
    // setLocale //
    //-----------//
    /**
     * Set application locale value.
     *
     * @param locale value to set
     */
    public static void setLocale (Locale locale)
    {
        if (!Locale.getDefault().equals(locale)) {
            constants.locale.setValue(locale.toString());
            Locale.setDefault(locale);
            logger.info("Locale set to: '{}'", locale);
        }
    }

    //-----------------//
    // showEnvironment //
    //-----------------//
    /**
     * Show the application environment to the user.
     */
    public static void showEnvironment ()
    {
        if (constants.showAllEnvironmentVariables.isSet()) {
            final Map<String, String> map = System.getenv();
            final TreeSet<String> keys = new TreeSet<>(map.keySet()); // Sorted
            keys.forEach(k -> logger.info("{} : {}", k, map.get(k)));
        }

        if (constants.showEnvironment.isSet()) {
            System.out.println(getEnvironment());
            System.out.println();
        }
    }

    private static String getEnvironment ()
    {
        return String.join(
                WellKnowns.LINE_SEPARATOR,
                WellKnowns.TOOL_DISPLAY_NAME,
                "- Version:      " + WellKnowns.TOOL_REF,
                "- Commit:       " + WellKnowns.TOOL_BUILD,
                "- OS:           " + System.getProperty("os.name") + //
                        " " + System.getProperty("os.version"),
                "- Architecture: " + System.getProperty("os.arch"),
                "- Java VM:      " + System.getProperty("java.vm.name") + //
                        " (build " + System.getProperty("java.vm.version") + //
                        ", " + System.getProperty("java.vm.info") + ")",
                "- OCR Engine:   " + TesseractOCR.getInstance().identify());
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Boolean showEnvironment = new Constant.Boolean(
                true,
                "Should we show environment?");

        private final Constant.Boolean showAllEnvironmentVariables = new Constant.Boolean(
                false,
                "Should we show all environment variables?");

        private final Constant.String locale = new Constant.String(
                "zh_CN",
                "Locale language to be used in the whole application (en, fr, zh_CN)");

        private final Constant.String supportedLocales = new Constant.String(
                "en,fr,zh_CN",
                "Comma-separated list of supported locale languages");

        private final Constant.Boolean persistBatchCliConstants = new Constant.Boolean(
                false,
                "Should we persist CLI-defined constants when running in batch?");

        private final Constant.Boolean runBatchTasksInParallel = new Constant.Boolean(
                false,
                "Should we process all tasks in parallel when running in batch?");

        private final Constant.Integer sheetStepTimeOut = new Constant.Integer(
                "Seconds",
                120,
                "Time-out for one step on a sheet, specified in seconds");
    }
}
