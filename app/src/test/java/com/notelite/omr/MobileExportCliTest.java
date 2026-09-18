package com.notelite.omr;

import java.nio.file.Paths;
import org.junit.Test;
import static org.junit.Assert.*;

/** Contract used by the Apple client's recognition bridge. */
public class MobileExportCliTest
{
    @Test
    public void parsesBothExportFormatsAndLiteralInput () throws Exception
    {
        CLI.Parameters params = new CLI("NoteLite").parseParameters(new String[] {
                "-batch", "-transcribe", "-export", "-export-midi", "-output", "out",
                "--", "-score with spaces.pdf" });
        assertTrue(params.batchMode);
        assertTrue(params.transcribe);
        assertTrue(params.export);
        assertTrue(params.exportMidi);
        assertEquals(Paths.get("out"), params.outputFolder);
        assertEquals(Paths.get("-score with spaces.pdf"), params.arguments.get(0));
    }

    @Test
    public void existingExportDoesNotRequestMidi () throws Exception
    {
        CLI.Parameters params = new CLI("NoteLite").parseParameters(new String[] {
                "-batch", "-export", "score.pdf" });
        assertTrue(params.export);
        assertFalse(params.exportMidi);
    }
}
