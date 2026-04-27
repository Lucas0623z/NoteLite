//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                   S e c t i o n S e r v i c e                                  //
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
package com.notelite.omr.lag;

import com.notelite.omr.ui.ViewParameters;
import com.notelite.omr.ui.selection.EntityListEvent;
import com.notelite.omr.ui.selection.EntityService;
import com.notelite.omr.ui.selection.IdEvent;
import com.notelite.omr.ui.selection.LocationEvent;
import com.notelite.omr.ui.selection.SelectionService;
import com.notelite.omr.util.EntityIndex;

/**
 * Class <code>SectionService</code> is an EntityService for sections.
 *
 * @author NoteLite Contributors
 */
@SuppressWarnings("unchecked")
public class SectionService
        extends EntityService<Section>
{
    //~ Static fields/initializers -----------------------------------------------------------------

    /** Events that can be published on section service. */
    private static final Class<?>[] eventsAllowed = new Class<?>[]
    { IdEvent.class, EntityListEvent.class };

    //~ Constructors -------------------------------------------------------------------------------

    /**
     * Creates a new <code>SectionService</code> object.
     *
     * @param index           underlying section index (typically a lag)
     * @param locationService related service for location info
     */
    public SectionService (EntityIndex<Section> index,
                           SelectionService locationService)
    {
        super(index, locationService, eventsAllowed);
    }

    //~ Methods ------------------------------------------------------------------------------------

    //---------------------//
    // handleLocationEvent //
    //---------------------//
    /**
     * Interest in location &rArr; list
     *
     * @param locationEvent the location event
     */
    @Override
    protected void handleLocationEvent (LocationEvent locationEvent)
    {
        // Search only when in MODE_SECTION
        if (ViewParameters.getInstance()
                .getSelectionMode() == ViewParameters.SelectionMode.MODE_SECTION) {
            super.handleLocationEvent(locationEvent);
        }
    }
}
