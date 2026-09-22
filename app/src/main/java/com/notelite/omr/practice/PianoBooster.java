/* Copyright © NoteLite 2026. Released under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import com.notelite.omr.OMR;
import com.notelite.omr.WellKnowns;
import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.score.MidiExporter;
import com.notelite.omr.score.Score;
import com.notelite.omr.sheet.Book;
import com.notelite.omr.sheet.ui.BookActions;
import com.notelite.omr.ui.util.WebBrowser;
import com.notelite.omr.util.BasicTask;
import java.awt.Component;
import java.io.IOException;
import java.net.URI;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.text.MessageFormat;
import java.util.ArrayList;
import java.util.List;
import java.util.ResourceBundle;
import javax.swing.JFileChooser;
import javax.swing.JOptionPane;
import javax.swing.SwingWorker;
import javax.swing.filechooser.FileNameExtensionFilter;

/** Product bridge: score transcription -> selected movement MIDI -> PianoBooster application. */
public final class PianoBooster
{
    private static final Constants constants = new Constants();
    private static final ResourceBundle strings = ResourceBundle.getBundle(
            "com.notelite.omr.practice.resources.PianoBooster");

    private PianoBooster () {}

    private static Component parent () { return OMR.gui.getFrame(); }
    private static String text (String key) { return strings.getString(key); }

    public static void open (Book book)
    {
        if (book == null || !BookActions.checkParameters(book)) return;
        new BasicTask<List<Movement>, Void>() {
            @Override protected List<Movement> doInBackground () throws Exception
            {
                if (!book.transcribe(book.getValidSelectedStubs(), book.getScores(), false)) {
                    throw new IOException(text("incomplete"));
                }
                List<Movement> movements = new ArrayList<>();
                Path folder = Files.createTempDirectory(WellKnowns.TEMP_FOLDER, "pianobooster-");
                for (Score score : book.getScores()) {
                    String name = book.getRadix().replaceAll("[^\\p{L}\\p{N}._-]", "_");
                    Path midi = folder.resolve(name + "-movement-" + score.getId() + ".mid");
                    new MidiExporter(score).export(midi);
                    movements.add(new Movement(score.getId(), midi));
                }
                if (movements.isEmpty()) throw new IOException(text("incomplete"));
                return movements;
            }

            @Override protected void succeeded (List<Movement> movements)
            {
                Movement selected = movements.get(0);
                if (movements.size() > 1) {
                    selected = (Movement) JOptionPane.showInputDialog(parent(), text("chooseMovement"),
                            text("title"), JOptionPane.QUESTION_MESSAGE, null, movements.toArray(), selected);
                }
                if (selected != null) openMidi(selected.midi);
            }

            @Override protected void failed (Throwable error) { showError(error); }
        }.execute();
    }

    /** Also called from the menu when no book is open, so a moved installation can be reconfigured. */
    public static void configure ()
    {
        chooseExecutable();
    }

    /** Open MIDI from an external recognizer/editor without requiring a NoteLite book. */
    public static void importMidi ()
    {
        JFileChooser chooser = new JFileChooser();
        chooser.setDialogTitle(text("importMidi"));
        chooser.setFileSelectionMode(JFileChooser.FILES_ONLY);
        chooser.setFileFilter(new FileNameExtensionFilter("MIDI (*.mid, *.midi)", "mid", "midi"));
        if (chooser.showOpenDialog(parent()) == JFileChooser.APPROVE_OPTION) {
            openMidi(chooser.getSelectedFile().toPath().toAbsolutePath());
        }
    }

    private static Path chooseExecutable ()
    {
        JFileChooser chooser = new JFileChooser();
        chooser.setDialogTitle(text("chooseExecutable"));
        chooser.setFileSelectionMode(JFileChooser.FILES_AND_DIRECTORIES);
        PianoBoosterLauncher.find(constants.executablePath.getValue())
                .ifPresent(path -> chooser.setSelectedFile(path.toFile()));
        while (chooser.showOpenDialog(parent()) == JFileChooser.APPROVE_OPTION) {
            Path selected = chooser.getSelectedFile().toPath();
            var executable = PianoBoosterLauncher.executable(selected);
            if (executable.isPresent()) {
                constants.executablePath.setValue(executable.get().toString());
                return executable.get();
            }
            JOptionPane.showMessageDialog(parent(), text("invalidExecutable"), text("title"), JOptionPane.ERROR_MESSAGE);
        }
        return null;
    }

    private static void openMidi (Path midi)
    {
        Path executable = PianoBoosterLauncher.find(constants.executablePath.getValue()).orElse(null);
        while (executable == null) {
            Object[] choices = { text("locate"), text("download"), text("saveMidi"), text("cancel") };
            int choice = JOptionPane.showOptionDialog(parent(), text("missing"), text("title"),
                    JOptionPane.DEFAULT_OPTION, JOptionPane.INFORMATION_MESSAGE, null, choices, choices[0]);
            if (choice == 0) executable = chooseExecutable();
            else if (choice == 1) WebBrowser.getBrowser().launch(URI.create(PianoBoosterLauncher.DOWNLOAD_URL));
            else if (choice == 2) { saveMidi(midi); return; }
            else return;
        }
        Path selectedExecutable = executable;
        new SwingWorker<Void, Void>() {
            @Override protected Void doInBackground () throws Exception
            {
                PianoBoosterLauncher.launch(selectedExecutable, midi);
                return null;
            }

            @Override protected void done ()
            {
                try {
                    get();
                } catch (Exception error) {
                    showError(error.getCause() != null ? error.getCause() : error);
                    saveMidi(midi);
                }
            }
        }.execute();
    }

    private static void saveMidi (Path midi)
    {
        JFileChooser chooser = new JFileChooser();
        chooser.setDialogTitle(text("saveMidi"));
        chooser.setFileFilter(new FileNameExtensionFilter("MIDI (*.mid)", "mid"));
        chooser.setSelectedFile(midi.getFileName().toFile());
        if (chooser.showSaveDialog(parent()) != JFileChooser.APPROVE_OPTION) return;
        Path target = chooser.getSelectedFile().toPath();
        if (!target.getFileName().toString().toLowerCase(java.util.Locale.ROOT).endsWith(".mid")) {
            target = target.resolveSibling(target.getFileName() + ".mid");
        }
        if (Files.exists(target) && JOptionPane.showConfirmDialog(parent(), text("overwrite"), text("title"),
                JOptionPane.YES_NO_OPTION) != JOptionPane.YES_OPTION) return;
        try {
            Files.copy(midi, target, StandardCopyOption.REPLACE_EXISTING);
        } catch (IOException error) { showError(error); }
    }

    private static void showError (Throwable error)
    {
        JOptionPane.showMessageDialog(parent(), text("error") + "\n" + error.getMessage(),
                text("title"), JOptionPane.ERROR_MESSAGE);
    }

    private static final class Movement
    {
        final int id;
        final Path midi;
        Movement (int id, Path midi) { this.id = id; this.midi = midi; }
        @Override public String toString () { return MessageFormat.format(text("movement"), id); }
    }

    private static final class Constants extends ConstantSet
    {
        private final Constant.String executablePath = new Constant.String("",
                "Path to an independently installed PianoBooster executable (blank for auto-discovery)");
    }
}
