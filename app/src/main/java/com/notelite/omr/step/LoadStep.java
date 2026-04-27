//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        L o a d S t e p                                         //
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
package com.notelite.omr.step;

import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.sheet.Sheet;
import com.notelite.omr.sheet.SheetStub;
import com.notelite.omr.sheet.ui.SheetTab;
import com.notelite.omr.util.Memory;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.awt.image.BufferedImage;

/**
 * Class <code>LoadStep</code> loads the image for a sheet, from a provided image file.
 *
 * @author NoteLite Contributors
 */
public class LoadStep
        extends AbstractStep
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    private static final Logger logger = LoggerFactory.getLogger(LoadStep.class);

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new LoadStep object.
     */
    public LoadStep ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //------//
    // doit //
    //------//
    @Override
    public void doit (Sheet sheet)
        throws StepException
    {
        final SheetStub stub = sheet.getStub();
        final BufferedImage image = stub.loadGrayImage();

        if (image == null) {
            throw new StepException("No image");
        } else {
            // Threshold on image size
            final int count = image.getWidth() * image.getHeight();
            final int max = constants.maxPixelCount.getValue();

            if ((max > 0) && (count > max)) {
                Memory.gc();

                ///logger.info("Occupied memory: {}", Memory.getValue());
                final String msg = "Too large image: " + String.format("%,d", count)
                        + " pixels (vs " + String.format("%,d", max) + " max)";
                stub.decideOnRemoval(msg, false); // This may throw StepException
            }

            sheet.setImage(image, true);
        }
    }

    //-------------//
    // getSheetTab //
    //-------------//
    @Override
    public SheetTab getSheetTab ()
    {
        return SheetTab.GRAY_TAB;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Integer maxPixelCount = new Constant.Integer( //
                "Pixels", //
                20_000_000, //
                "Maximum image size, specified in pixel count (0 for no check)");
    }
}
