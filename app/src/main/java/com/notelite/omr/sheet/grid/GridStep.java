//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        G r i d S t e p                                         //
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
package com.notelite.omr.sheet.grid;

import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.sheet.Picture;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.ui.ImageView;
import com.notelite.omr.sheet.ui.PixelBoard;
import com.notelite.omr.sheet.ui.ScrollImageView;
import com.notelite.omr.sheet.ui.SheetTab;
import com.notelite.omr.step.AbstractStep;
import com.notelite.omr.step.OmrStep;
import com.notelite.omr.step.StepException;
import com.notelite.omr.ui.BoardsPane;
import com.notelite.omr.util.StopWatch;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Class <code>GridStep</code> implements the <b>GRID</b> step, which retrieves all staves and
 * systems of a sheet.
 *
 * @author NoteLite Contributors
 */
public class GridStep
        extends AbstractStep
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(GridStep.class);

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new GridStep object.
     */
    public GridStep ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-----------//
    // displayUI //
    //-----------//
    @Override
    public void displayUI (OmrStep step,
                           Sheet sheet)
    {
        sheet.getSheetEditor().refresh();

        if (constants.displayNoStaff.isSet()) {
            sheet.getStub().getAssembly().addViewTab(
                    SheetTab.NO_STAFF_TAB,
                    new ScrollImageView(
                            sheet,
                            new ImageView(
                                    sheet.getPicture().getSource(Picture.SourceKey.NO_STAFF)
                                            .getBufferedImage())),
                    new BoardsPane(new PixelBoard(sheet)));
        }
    }

    //------//
    // doit //
    //------//
    @Override
    public void doit (Sheet sheet)
        throws StepException
    {
        final StopWatch watch = new StopWatch("GridStep");
        watch.start("GridBuilder");
        new GridBuilder(sheet).buildInfo();

        watch.start("StaffLineCleaner");
        new StaffLineCleaner(sheet).process();

        watch.start("book.updateScores");
        sheet.getStub().getBook().updateScores(sheet.getStub());

        if (constants.printWatch.isSet())
            watch.print();
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Boolean printWatch = new Constant.Boolean(
                false,
                "Should we print out the stop watch?");

        private final Constant.Boolean displayNoStaff = new Constant.Boolean(
                false,
                "Should we display the staff-free image?");
    }
}
