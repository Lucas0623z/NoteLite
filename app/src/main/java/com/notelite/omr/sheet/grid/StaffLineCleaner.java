//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                 S t a f f L i n e C l e a n e r                                //
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
import com.notelite.omr.glyph.dynamic.SectionCompound;
import com.notelite.omr.lag.Lag;
import com.notelite.omr.lag.Lags;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.Staff;
import com.notelite.omr.util.Navigable;
import com.notelite.omr.util.StopWatch;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.List;

/**
 * Class <code>StaffLineCleaner</code> handles the "removal" of staff line pixels.
 * <ol>
 * <li>It removes from global {@link Lags#HLAG} lag the (horizontal) sections used by staff lines.
 * <li>It dispatches vertical and remaining horizontal sections into their containing system(s).
 * </ol>
 *
 * @author NoteLite Contributors
 */
public class StaffLineCleaner
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(StaffLineCleaner.class);

    //~ Instance fields ----------------------------------------------------------------------------

    /** Related sheet. */
    @Navigable(false)
    private final Sheet sheet;

    /** Horizontal lag. */
    private final Lag hLag;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>StaffLineCleaner</code> object.
     *
     * @param sheet the related sheet, which holds the v and h lags
     */
    public StaffLineCleaner (Sheet sheet)
    {
        this.sheet = sheet;

        hLag = sheet.getLagManager().getLag(Lags.HLAG);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------//
    // process //
    //---------//
    /**
     * Clean the staff lines by "removing" the line glyphs.
     */
    public void process ()
    {
        final StopWatch watch = new StopWatch("StaffLineCleaner");

        // Replace staff line filaments by lighter data
        watch.start("simplify staff lines");

        for (Staff staff : sheet.getStaffManager().getStaves()) {
            final List<LineInfo> originals = staff.simplifyLines(sheet);

            // Remove staff line original sections from hLag
            for (LineInfo line : originals) {
                hLag.removeSections(((SectionCompound) line).getMembers());
            }
        }

        // Regenerate hLag from noStaff buffer
        sheet.getLagManager().rebuildHLag();

        // Dispatch sections to relevant systems
        watch.start("populate systems");
        sheet.getSystemManager().populateSystems();

        if (constants.printWatch.isSet()) {
            watch.print();
        }
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
    }
}
