//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                    F i l a m e n t B o a r d                                   //
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
package com.notelite.omr.glyph.dynamic;

import com.notelite.omr.ui.Board;
import com.notelite.omr.ui.EntityBoard;
import com.notelite.omr.ui.selection.EntityService;

/**
 * Class <code>FilamentBoard</code> is an EntityBoard for filaments.
 *
 * @author NoteLite Contributors
 */
public class FilamentBoard
        extends EntityBoard<Filament>
{
    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>FilamentBoard</code> object.
     *
     * @param service  filament service
     * @param selected true for pre-selected
     */
    public FilamentBoard (EntityService<Filament> service,
                          boolean selected)
    {
        super(Board.FILAMENT, service, selected);
    }
}
