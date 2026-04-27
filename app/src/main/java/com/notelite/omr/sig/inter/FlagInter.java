//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                        F l a g I n t e r                                       //
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
package com.notelite.omr.sig.inter;

import com.notelite.omr.glyph.Glyph;
import com.notelite.omr.glyph.Shape;
import com.notelite.omr.sheet.Part;
import com.notelite.omr.sheet.Staff;
import com.notelite.omr.sheet.rhythm.MeasureStack;
import com.notelite.omr.sig.relation.FlagStemRelation;
import com.notelite.omr.sig.relation.HeadStemRelation;
import com.notelite.omr.sig.relation.Relation;

import javax.xml.bind.annotation.XmlRootElement;

/**
 * Class <code>FlagInter</code> represents one or several flags.
 *
 * @author NoteLite Contributors
 */
@XmlRootElement(name = "flag")
public class FlagInter
        extends AbstractFlagInter
{
    //~ Constructors -------------------------------------------------------------------------------

    /**
     * No-argument constructor meant for JAXB.
     */
    protected FlagInter ()
    {
    }

    /**
     * Creates a new FlagInter object.
     *
     * @param glyph underlying glyph
     * @param shape precise shape
     * @param grade evaluation value
     */
    public FlagInter (Glyph glyph,
                      Shape shape,
                      Double grade)
    {
        super(glyph, shape, grade);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-------//
    // added //
    //-------//
    /**
     * Make sure containing stack is updated.
     *
     * @see #remove(boolean)
     */
    @Override
    public void added ()
    {
        super.added();

        MeasureStack stack = sig.getSystem().getStackAt(getCenter());

        if (stack != null) {
            stack.addInter(this);
        }

        setAbnormal(true); // No stem linked yet
    }

    //---------------//
    // checkAbnormal //
    //---------------//
    @Override
    public boolean checkAbnormal ()
    {
        // Check if flag is connected to a stem
        setAbnormal(!sig.hasRelation(this, FlagStemRelation.class));

        return isAbnormal();
    }

    //---------//
    // getPart //
    //---------//
    @Override
    public Part getPart ()
    {
        if (part == null) {
            // Flag -> Stem
            for (Relation fsRel : sig.getRelations(this, FlagStemRelation.class)) {
                StemInter stem = (StemInter) sig.getOppositeInter(this, fsRel);

                // Stem -> Head
                for (Relation hsRel : sig.getRelations(stem, HeadStemRelation.class)) {
                    Inter head = sig.getOppositeInter(stem, hsRel);

                    return part = head.getPart();
                }
            }
        }

        return super.getPart();
    }

    //----------//
    // getStaff //
    //----------//
    @Override
    public Staff getStaff ()
    {
        if (staff == null) {
            // Flag -> Stem
            for (Relation fsRel : sig.getRelations(this, FlagStemRelation.class)) {
                StemInter stem = (StemInter) sig.getOppositeInter(this, fsRel);

                // Stem -> Head
                for (Relation hsRel : sig.getRelations(stem, HeadStemRelation.class)) {
                    Inter head = sig.getOppositeInter(stem, hsRel);

                    return staff = head.getStaff();
                }
            }
        }

        return staff;
    }

    //--------//
    // remove //
    //--------//
    /**
     * Remove it from containing stack.
     *
     * @param extensive true for non-manual removals only
     * @see #added()
     */
    @Override
    public void remove (boolean extensive)
    {
        if (isRemoved()) {
            return;
        }

        MeasureStack stack = sig.getSystem().getStackAt(getCenter());

        if (stack != null) {
            stack.removeInter(this);
        }

        super.remove(extensive);
    }
}
