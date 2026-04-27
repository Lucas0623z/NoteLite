//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        S t a c k T a s k                                       //
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
package com.notelite.omr.sig.ui;

import com.notelite.omr.sheet.rhythm.MeasureStack;

/**
 * Class <code>StackTask</code> implements the on demand re-processing of a stack.
 *
 * @author NoteLite Contributors
 */
public class StackTask
        extends UITask
{
    //~ Instance fields ----------------------------------------------------------------------------

    /** Impacted stack. */
    private final MeasureStack stack;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>StackTask</code> object.
     *
     * @param stack the impacted stack
     */
    public StackTask (MeasureStack stack)
    {
        super(stack.getSystem().getSig(), "reprocess-stack");
        this.stack = stack;
    }

    //~ Methods ------------------------------------------------------------------------------------

    public MeasureStack getStack ()
    {
        return stack;
    }

    @Override
    public void performDo ()
    {
        // Void
    }

    @Override
    public void performUndo ()
    {
        // Void
    }
}
