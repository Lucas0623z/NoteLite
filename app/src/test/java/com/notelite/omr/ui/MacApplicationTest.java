package com.notelite.omr.ui;

import org.junit.Test;

import java.awt.event.InputEvent;
import java.awt.event.KeyEvent;

import javax.swing.JMenu;
import javax.swing.JMenuBar;
import javax.swing.JMenuItem;
import javax.swing.KeyStroke;

import static org.junit.Assert.*;

/** Shortcut conversion is testable without an Apple desktop or native application handlers. */
public class MacApplicationTest
{
    @Test
    public void commandShortcutsPreserveShiftAndRelease ()
    {
        KeyStroke original = KeyStroke.getKeyStroke(KeyEvent.VK_Z,
                InputEvent.CTRL_DOWN_MASK | InputEvent.SHIFT_DOWN_MASK, true);
        KeyStroke converted = MacApplication.commandShortcut(original);

        assertEquals(KeyEvent.VK_Z, converted.getKeyCode());
        assertEquals(0, converted.getModifiers() & InputEvent.CTRL_DOWN_MASK);
        assertNotEquals(0, converted.getModifiers() & InputEvent.META_DOWN_MASK);
        assertNotEquals(0, converted.getModifiers() & InputEvent.SHIFT_DOWN_MASK);
        assertTrue(converted.isOnKeyRelease());
    }

    @Test
    public void leavesFunctionKeysAndMissingShortcutsUnchanged ()
    {
        KeyStroke functionKey = KeyStroke.getKeyStroke(KeyEvent.VK_F8, 0);
        assertSame(functionKey, MacApplication.commandShortcut(functionKey));
        assertNull(MacApplication.commandShortcut(null));
    }

    @Test
    public void adaptsNestedMenusAndToleratesSeparators ()
    {
        JMenuBar bar = new JMenuBar();
        JMenu file = new JMenu("File");
        JMenu export = new JMenu("Export");
        JMenuItem save = new JMenuItem("Save");
        save.setAccelerator(KeyStroke.getKeyStroke("control S"));
        export.addSeparator();
        export.add(save);
        file.add(export);
        bar.add(file);

        MacApplication.adaptMenuShortcuts(bar);

        assertEquals(KeyStroke.getKeyStroke("meta S"), save.getAccelerator());
    }
}
