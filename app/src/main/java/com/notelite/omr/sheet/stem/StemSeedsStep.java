//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    S t e m S e e d s S t e p                                   //
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
package com.notelite.omr.sheet.stem;

import com.notelite.omr.sheet.Scale.StemScale;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.SystemInfo;
import com.notelite.omr.step.AbstractSystemStep;
import com.notelite.omr.step.OmrStep;
import com.notelite.omr.step.StepException;
import com.notelite.omr.ui.action.Preferences;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Class <code>StemSeedsStep</code> implements <b>STEM_SEEDS</b> step, which retrieves all
 * vertical sticks that may constitute <i>seeds</i> of future stems.
 *
 * @author NoteLite Contributors
 */
public class StemSeedsStep
        extends AbstractSystemStep<Void>
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Logger logger = LoggerFactory.getLogger(StemSeedsStep.class);

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new StemSeedsStep object.
     */
    public StemSeedsStep ()
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
        if (Preferences.Topic.DEBUG.isSet()) {
            // Add stem checkboard
            new StemChecker(sheet).addCheckBoard();
        }
    }

    //----------//
    // doProlog //
    //----------//
    @Override
    protected Void doProlog (Sheet sheet)
        throws StepException
    {
        StemScale stemScale = sheet.getScale().getStemScale();

        // Respect user-assigned stem scale if any
        if (stemScale == null) {
            // Retrieve typical stem width on global sheet
            stemScale = new StemScaler(sheet).retrieveStemWidth();

            logger.info("{}", stemScale);
            sheet.getScale().setStemScale(stemScale);
        }

        return null;
    }

    //----------//
    // doSystem //
    //----------//
    @Override
    public void doSystem (SystemInfo system,
                          Void context)
        throws StepException
    {
        new VerticalsBuilder(system).buildVerticals(); // -> Stem seeds
    }
}
