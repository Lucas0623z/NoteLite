//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                              C h o r d T u p l e t R e l a t i o n                             //
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
package com.notelite.omr.sig.relation;

import com.notelite.omr.constant.Constant;
import com.notelite.omr.constant.ConstantSet;
import com.notelite.omr.glyph.Shape;
import com.notelite.omr.sig.inter.Inter;
import com.notelite.omr.sig.inter.TupletInter;

import org.jgrapht.event.GraphEdgeChangeEvent;

import javax.xml.bind.annotation.XmlRootElement;

/**
 * Class <code>ChordTupletRelation</code> represents the relation between a chord and an
 * embracing tuplet sign.
 *
 * @author NoteLite Contributors
 */
@XmlRootElement(name = "chord-tuplet")
public class ChordTupletRelation
        extends Support
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    //~ Instance fields ----------------------------------------------------------------------------

    /** Assigned tuplet support coefficient. */
    private final double tupletCoeff;

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * No-argument constructor meant for JAXB and user allocation.
     */
    public ChordTupletRelation ()
    {
        this.tupletCoeff = 0;
    }

    /**
     * Creates a new <code>TupletChordRelation</code> object.
     *
     * @param shape the tuplet shape (currently either TUPLET_THREE or TUPLET_SIX)
     */
    public ChordTupletRelation (Shape shape)
    {
        tupletCoeff = getTupletCoeff(shape);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //-------//
    // added //
    //-------//
    @Override
    public void added (GraphEdgeChangeEvent<Inter, Relation> e)
    {
        final TupletInter tuplet = (TupletInter) e.getEdgeTarget();

        if (!tuplet.isImplicit()) {
            tuplet.checkAbnormal();
        }
    }

    //----------------//
    // getTargetCoeff //
    //----------------//
    @Override
    protected double getTargetCoeff ()
    {
        return tupletCoeff;
    }

    //----------------//
    // getTupletCoeff //
    //----------------//
    private double getTupletCoeff (Shape shape)
    {
        return switch (shape) {
            case TUPLET_THREE -> constants.tupletThreeSupportCoeff.getValue();
            case TUPLET_SIX -> constants.tupletSixSupportCoeff.getValue();
            default -> throw new IllegalArgumentException("Illegal tuplet shape " + shape);
        };
    }

    //----------------//
    // isSingleSource //
    //----------------//
    @Override
    public boolean isSingleSource ()
    {
        return false;
    }

    //----------------//
    // isSingleTarget //
    //----------------//
    @Override
    public boolean isSingleTarget ()
    {
        return true;
    }

    //---------//
    // removed //
    //---------//
    @Override
    public void removed (GraphEdgeChangeEvent<Inter, Relation> e)
    {
        final TupletInter tuplet = (TupletInter) e.getEdgeTarget();

        if (!tuplet.isRemoved() && !tuplet.isImplicit()) {
            tuplet.checkAbnormal();
        }
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Ratio tupletThreeSupportCoeff = new Constant.Ratio(
                2 * 0.33,
                "Supporting coeff for tuplet 3");

        private final Constant.Ratio tupletSixSupportCoeff = new Constant.Ratio(
                2 * 0.17,
                "Supporting coeff for tuplet 6");
    }
}
