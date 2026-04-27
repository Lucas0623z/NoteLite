//------------------------------------------------------------------------------------------------//
//                                                                                                //
//                                   N o t e L i t e       T e s t                                    //
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

import org.junit.Test;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Test for multiple calls of NoteLite
 *
 * @author NoteLite Contributors
 */
public class NoteLiteTest
{

    private static final Logger logger = LoggerFactory.getLogger(NoteLiteTest.class);

    /**
     * Creates a new NoteLiteTest object.
     */
    public NoteLiteTest ()
    {
    }

    /**
     * Test of main method, of class NoteLite.
     */
    @Test
    public void testMultipleCalls ()
    {
        System.out.println("testMultipleCalls");

        String[] args1 = new String[]{
            "-batch", "-step", "EXPORT", "-input", "data/examples/chula.png"
        };
        String[] args2 = new String[]{
            "-batch", "-step", "EXPORT", "-input", "data/examples/batuque.png",
            "data/examples/allegretto.png"
        };

        //        System.out.println("firstCall to NoteLite.main()");
        //        logger.info("firstCall to NoteLite.main()");
        //        NoteLite.main(args1);
        //        System.out.println("secondCall to NoteLite.main()");
        //        logger.info("secondCall to NoteLite.main()");
        //        NoteLite.main(args2);
        //        System.out.println("finished");
    }
}
