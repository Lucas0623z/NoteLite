//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        S t e p M e n u                                         //
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
package com.notelite.omr.step.ui;

import com.notelite.omr.OMR;
import com.notelite.omr.log.LogUtil;
import com.notelite.omr.sheet.Picture;
import com.notelite.omr.sheet.SheetStub;
import com.notelite.omr.sheet.ui.StubsController;
import com.notelite.omr.step.OmrStep;
import com.notelite.omr.step.ProcessingCancellationException;
import com.notelite.omr.ui.util.AbstractMenuListener;
import com.notelite.omr.util.VoidTask;

import org.jdesktop.application.Application;
import org.jdesktop.application.ResourceMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.awt.event.ActionEvent;
import java.nio.file.Files;
import java.nio.file.Path;

import javax.swing.AbstractAction;
import javax.swing.JCheckBoxMenuItem;
import javax.swing.JMenu;
import javax.swing.JMenuItem;
import javax.swing.JOptionPane;
import javax.swing.event.MenuEvent;

/**
 * Class <code>StepMenu</code> encapsulates the user interface needed to deal with
 * application steps.
 * Steps are represented by menu items, each one being a check box, to indicate the current status
 * regarding the execution of the step (done or not done).
 *
 * @author NoteLite Contributors
 */
public class StepMenu
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(StepMenu.class);

    private static final ResourceMap resources = Application.getInstance().getContext()
            .getResourceMap(StepMenu.class);

    //~ Instance fields ----------------------------------------------------------------------------

    /** The concrete UI menu. */
    private final JMenu menu;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Generates the menu to be inserted in the application pull-down menus.
     *
     * @param menu the hosting menu, or null
     */
    public StepMenu (JMenu menu)
    {
        if (menu == null) {
            menu = new JMenu();
        }

        this.menu = menu;

        // Build the menu content
        updateMenu();

        // Listener to modify attributes on-the-fly
        menu.addMenuListener(new MyMenuListener());
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------//
    // getMenu //
    //---------//
    /**
     * Report the concrete UI menu.
     *
     * @return the menu entity
     */
    public JMenu getMenu ()
    {
        return menu;
    }

    //------------//
    // updateMenu //
    //------------//
    /**
     * Update/rebuild the content of menu.
     */
    public final void updateMenu ()
    {
        menu.removeAll();

        // List of Steps classes in proper order
        for (OmrStep step : OmrStep.values()) {
            menu.add(new StepItem(step));
        }
    }

    //----------------//
    // MyMenuListener //
    //----------------//
    /**
     * Class <code>MyMenuListener</code> is triggered when the whole sub-menu is entered.
     * This is done with respect to currently displayed sheet.
     * The steps already done are flagged as such.
     */
    private class MyMenuListener
            extends AbstractMenuListener
    {
        @Override
        public void menuSelected (MenuEvent e)
        {
            SheetStub stub = StubsController.getCurrentStub();
            boolean isIdle = (stub != null) && (stub.getCurrentStep() == null);

            for (int i = 0; i < menu.getItemCount(); i++) {
                JMenuItem menuItem = menu.getItem(i);

                // Adjust the status for each step
                if (menuItem instanceof StepItem) {
                    StepItem item = (StepItem) menuItem;
                    item.displayState(stub, isIdle);
                }
            }
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //------------//
    // StepAction //
    //------------//
    private static class StepAction
            extends AbstractAction
    {
        // The related step
        OmrStep step;

        StepAction (OmrStep step)
        {
            super(localizedName(step));
            this.step = step;
            putValue(SHORT_DESCRIPTION, localizedDescription(step));
        }

        private static String localizedName (OmrStep step)
        {
            final String key = step.name() + ".text";
            if (resources != null && resources.containsKey(key)) {
                return resources.getString(key);
            }
            return step.toString();
        }

        private static String localizedDescription (OmrStep step)
        {
            final String key = step.name() + ".description";
            if (resources != null && resources.containsKey(key)) {
                return resources.getString(key);
            }
            return step.getDescription();
        }

        @Override
        public void actionPerformed (ActionEvent e)
        {
            final SheetStub stub = StubsController.getCurrentStub();
            new VoidTask()
            {
                @Override
                protected Void doInBackground ()
                    throws Exception
                {
                    try {
                        OmrStep sofar = stub.getLatestStep();

                        if ((sofar != null) && (sofar.compareTo(step) >= 0)) {
                            // Make sure proper source is available for LOAD or BINARY target steps
                            if (step == OmrStep.LOAD) {
                                final Path inputPath = stub.getBook().getInputPath();

                                if (!Files.exists(inputPath)) {
                                    OMR.gui.displayWarning(
                                            "Input file not found: " + inputPath,
                                            "No source for " + step + " step");
                                    step = null;

                                    return null;
                                }
                            } else if (step == OmrStep.BINARY) {
                                final Picture picture = stub.getSheet().getPicture();

                                if (null == picture.getSource(Picture.SourceKey.GRAY)) {
                                    OMR.gui.displayWarning(
                                            "Gray source not found.",
                                            "No source for " + step + " step");
                                    step = null;

                                    return null;
                                }
                            }

                            // Refine messages for very first steps (LOAD and BINARY)
                            final String mid = (step.compareTo(OmrStep.BINARY) <= 0) ? ""
                                    : " from binary source";

                            if (!OMR.gui.displayConfirmation(
                                    "About to re-perform step " + step + mid + "."
                                            + "\nDo you confirm?",
                                    "Redo confirmation",
                                    JOptionPane.YES_NO_OPTION,
                                    JOptionPane.WARNING_MESSAGE)) {
                                return null;
                            }
                        }

                        try {
                            LogUtil.start(stub);

                            stub.reachStep(step, true);
                            logger.info("End of sheet step {}", stub.getLatestStep());
                        } finally {
                            LogUtil.stopStub();
                        }
                    } catch (ProcessingCancellationException pce) {
                        logger.info("ProcessingCancellationException detected");
                    }

                    return null;
                }

                @Override
                protected void succeeded (Void result)
                {
                    if (stub != null) {
                        final OmrStep latestStep = stub.getLatestStep();

                        if (latestStep != null) {
                            // Select the assembly tab related to the latest step
                            StepMonitoring.notifyStep(stub, latestStep);
                        }
                    }
                }
            }.execute();
        }
    }

    //----------//
    // StepItem //
    //----------//
    /**
     * Class <code>StepItem</code> implements a checkable menu item linked to a given step.
     */
    private static class StepItem
            extends JCheckBoxMenuItem
    {
        StepItem (OmrStep step)
        {
            super(new StepAction(step));
        }

        public void displayState (SheetStub stub,
                                  boolean isIdle)
        {
            final StepAction action = (StepAction) getAction();

            if ((stub == null) || !stub.isValid()) {
                setState(false);
                action.setEnabled(false);
            } else {
                action.setEnabled(true);

                final boolean done = stub.isDone(action.step);
                setState(done);

                if (!isIdle) {
                    action.setEnabled(false);
                }
            }
        }
    }
}
