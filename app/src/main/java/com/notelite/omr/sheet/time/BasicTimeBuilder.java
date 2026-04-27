//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                 B a s i c T i m e B u i l d e r                                //
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
package com.notelite.omr.sheet.time;

import com.notelite.omr.sheet.Staff;
import com.notelite.omr.sig.inter.Inter;
import com.notelite.omr.sig.inter.TimeNumberInter;
import com.notelite.omr.sig.inter.TimeWholeInter;
import com.notelite.omr.util.VerticalSide;

/**
 * A subclass of TimeBuilder specifically meant for extraction outside system header,
 * further down in the system measures.
 * <p>
 * Symbol extraction has already been performed, so time-signature shaped symbols are now
 * checked for consistency across all staves of the containing system.
 *
 * @author NoteLite Contributors
 */
public class BasicTimeBuilder
        extends TimeBuilder
{
    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>BasicTimeBuilder</code> object.
     *
     * @param staff  underlying staff
     * @param column containing time column
     */
    public BasicTimeBuilder (Staff staff,
                             BasicTimeColumn column)
    {
        super(staff, column);
    }

    //~ Methods ------------------------------------------------------------------------------------

    @Override
    public void cleanup ()
    {
        throw new UnsupportedOperationException("Not supported yet.");
    }

    @Override
    protected void findCandidates ()
    {
        // For time symbols found (whole or half), pitch is correct, but abscissa is random
        // For now, at staff level, we can only check that nums & dens are x-compatible
        BasicTimeColumn basicColumn = (BasicTimeColumn) column;

        for (Inter inter : basicColumn.timeSet) {
            if (inter.getStaff() == staff) {
                if (inter instanceof TimeWholeInter) {
                    wholes.add(inter);
                } else if (inter instanceof TimeNumberInter) {
                    TimeNumberInter number = (TimeNumberInter) inter;
                    VerticalSide side = number.getSide();

                    if (side == VerticalSide.TOP) {
                        nums.add(inter);
                    } else {
                        dens.add(inter);
                    }
                }
            }
        }
    }
}
