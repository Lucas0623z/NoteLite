//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                       H e a d C o r n e r                                      //
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

import com.notelite.omr.util.HorizontalSide;
import static com.notelite.omr.util.HorizontalSide.LEFT;
import static com.notelite.omr.util.HorizontalSide.RIGHT;
import com.notelite.omr.util.VerticalSide;
import static com.notelite.omr.util.VerticalSide.BOTTOM;
import static com.notelite.omr.util.VerticalSide.TOP;

/**
 * Class <code>HeadCorner</code> defines the four corners suitable for head connection to stem.
 *
 * @author NoteLite Contributors
 */
public enum HeadCorner
{
    TOP_RIGHT(TOP, RIGHT),
    BOTTOM_LEFT(BOTTOM, LEFT),
    TOP_LEFT(TOP, LEFT),
    BOTTOM_RIGHT(BOTTOM, RIGHT);

    /** The vertical side. */
    public final VerticalSide vSide;

    /** The horizontal side. */
    public final HorizontalSide hSide;

    /**
     * Creates a new Corner object.
     *
     * @param vSide vertical side
     * @param hSide horizontal side
     */
    private HeadCorner (VerticalSide vSide,
                        HorizontalSide hSide)
    {
        this.vSide = vSide;
        this.hSide = hSide;
    }

    /**
     * Report the corner ID.
     *
     * @return id
     */
    public String getId ()
    {
        return "" + vSide.name().charAt(0) + '-' + hSide.name().charAt(0);
    }

    //----//
    // of //
    //----//
    public static HeadCorner of (VerticalSide vSide,
                                 HorizontalSide hSide)
    {
        return switch (vSide) {
            case TOP -> switch (hSide) {
                case LEFT -> TOP_LEFT;
                case RIGHT -> TOP_RIGHT;
            };

            case BOTTOM -> switch (hSide) {
                case LEFT -> BOTTOM_LEFT;
                case RIGHT -> BOTTOM_RIGHT;
            };
        };
    }
}
