//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                            T i m e T o p B o t t o m R e l a t i o n                           //
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
import com.notelite.omr.sig.inter.TimeNumberInter;

import javax.xml.bind.annotation.XmlRootElement;

/**
 * Class <code>TimeTopBottomRelation</code> represents the relation between a top
 * {@link TimeNumberInter} and a bottom {@link TimeNumberInter} in a time signature.
 *
 * @author NoteLite Contributors
 */
@XmlRootElement(name = "time-top-bottom")
public class TimeTopBottomRelation
        extends Support
{
    //~ Static fields/initializers -----------------------------------------------------------------

    private static final Constants constants = new Constants();

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>TimeTopBottomRelation</code> object.
     */
    public TimeTopBottomRelation ()
    {
    }

    //~ Methods ------------------------------------------------------------------------------------

    //----------------//
    // getSourceCoeff //
    //----------------//
    @Override
    protected double getSourceCoeff ()
    {
        return constants.numberSupportCoeff.getValue();
    }

    //----------------//
    // getTargetCoeff //
    //----------------//
    @Override
    protected double getTargetCoeff ()
    {
        return constants.numberSupportCoeff.getValue();
    }

    //----------------//
    // isSingleSource //
    //----------------//
    @Override
    public boolean isSingleSource ()
    {
        return true;
    }

    //----------------//
    // isSingleTarget //
    //----------------//
    @Override
    public boolean isSingleTarget ()
    {
        return true;
    }

    //~ Inner Classes ------------------------------------------------------------------------------

    //-----------//
    // Constants //
    //-----------//
    private static class Constants
            extends ConstantSet
    {
        private final Constant.Ratio numberSupportCoeff = new Constant.Ratio(
                5,
                "Value for (source/target) number coeff in support formula");
    }
}
