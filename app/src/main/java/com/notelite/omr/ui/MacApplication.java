//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                  M a c A p p l i c a t i o n                                   //
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
package com.notelite.omr.ui;

import com.notelite.omr.OMR;
import com.notelite.omr.WellKnowns;
import com.notelite.omr.sheet.ui.BookActions.LoadBookTask;
import com.notelite.omr.sheet.ui.BookActions.LoadImageTask;
import com.notelite.omr.util.UriUtil;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.awt.Desktop;
import java.awt.Taskbar;
import java.awt.event.InputEvent;
import java.io.File;
import java.net.MalformedURLException;
import java.net.URI;
import java.util.Locale;

import javax.swing.Action;
import javax.swing.ImageIcon;
import javax.swing.JMenu;
import javax.swing.JMenuBar;
import javax.swing.JMenuItem;
import javax.swing.KeyStroke;
import javax.swing.SwingUtilities;

/** macOS integration using the supported Java desktop APIs (Java 9 and later). */
public final class MacApplication
{
    private static final Logger logger = LoggerFactory.getLogger(MacApplication.class);

    private MacApplication ()
    {
    }

    /** Register native application-menu and Finder file-opening handlers. */
    public static boolean setupMacMenus ()
    {
        if (!WellKnowns.MAC_OS_X || !Desktop.isDesktopSupported()) {
            return false;
        }

        try {
            final Desktop desktop = Desktop.getDesktop();

            if (desktop.isSupported(Desktop.Action.APP_ABOUT)) {
                desktop.setAboutHandler(event -> onEventThread(
                        () -> GuiActions.getInstance().showAbout(null)));
            }
            if (desktop.isSupported(Desktop.Action.APP_PREFERENCES)) {
                desktop.setPreferencesHandler(event -> onEventThread(
                        () -> GuiActions.getInstance().definePreferences(null)));
            }
            if (desktop.isSupported(Desktop.Action.APP_QUIT_HANDLER)) {
                desktop.setQuitHandler((event, response) -> {
                    // BSAF owns shutdown and asks to save each modified book. Cancel the
                    // native automatic exit so declining that dialog keeps the app alive.
                    response.cancelQuit();
                    onEventThread(() -> GuiActions.getInstance().exit(null));
                });
            }
            if (desktop.isSupported(Desktop.Action.APP_OPEN_FILE)) {
                desktop.setOpenFileHandler(event -> onEventThread(() -> {
                    for (File file : event.getFiles()) {
                        if (!file.isFile()) {
                            logger.warn("Cannot open file from Finder: {}", file);
                            continue;
                        }
                        // Use the same background tasks as Open and drag-and-drop.
                        // Saved OMR projects must not be passed to the image reader.
                        if (file.getName().toLowerCase(Locale.ROOT).endsWith(OMR.BOOK_EXTENSION)) {
                            new LoadBookTask(file.toPath()).execute();
                        } else {
                            new LoadImageTask(file.toPath()).execute();
                        }
                    }
                }));
            }
            return true;
        } catch (UnsupportedOperationException | SecurityException ex) {
            logger.warn("Unable to set up macOS application integration", ex);
            return false;
        }
    }

    /** Set the Dock icon when launched using Gradle or a generated start script. */
    public static boolean setupMacDockIcon ()
    {
        if (!WellKnowns.MAC_OS_X || !Taskbar.isTaskbarSupported()) {
            return false;
        }

        try {
            final Taskbar taskbar = Taskbar.getTaskbar();
            if (!taskbar.isSupported(Taskbar.Feature.ICON_IMAGE)) {
                return false;
            }
            URI uri = UriUtil.toURI(WellKnowns.RES_URI, "icon-256.png");
            taskbar.setIconImage(new ImageIcon(uri.toURL()).getImage());
            return true;
        } catch (UnsupportedOperationException | SecurityException | MalformedURLException ex) {
            logger.warn("Unable to set up macOS Dock icon", ex);
            return false;
        }
    }

    /** Translate application menu shortcuts to the macOS Command convention. */
    public static void adaptMenuShortcuts (JMenuBar menuBar)
    {
        for (int i = 0; i < menuBar.getMenuCount(); i++) {
            final JMenu menu = menuBar.getMenu(i);
            if (menu != null) {
                adaptMenu(menu);
            }
        }
    }

    private static void adaptMenu (JMenu menu)
    {
        for (int i = 0; i < menu.getItemCount(); i++) {
            final JMenuItem item = menu.getItem(i);
            if (item instanceof JMenu child) {
                adaptMenu(child);
            } else if (item != null) {
                final KeyStroke shortcut = commandShortcut(item.getAccelerator());
                item.setAccelerator(shortcut);
                final Action action = item.getAction();
                if (action != null && shortcut != null) {
                    action.putValue(Action.ACCELERATOR_KEY, shortcut);
                }
            }
        }
    }

    @SuppressWarnings("deprecation") // KeyStroke includes both legacy and extended modifier bits.
    static KeyStroke commandShortcut (KeyStroke shortcut)
    {
        if (shortcut == null) {
            return null;
        }
        final int controlMask = InputEvent.CTRL_MASK | InputEvent.CTRL_DOWN_MASK;
        if ((shortcut.getModifiers() & controlMask) == 0) {
            return shortcut;
        }
        final int modifiers = (shortcut.getModifiers() & ~controlMask) | InputEvent.META_DOWN_MASK;
        return KeyStroke.getKeyStroke(shortcut.getKeyCode(), modifiers, shortcut.isOnKeyRelease());
    }

    private static void onEventThread (Runnable action)
    {
        if (SwingUtilities.isEventDispatchThread()) {
            action.run();
        } else {
            SwingUtilities.invokeLater(action);
        }
    }
}
