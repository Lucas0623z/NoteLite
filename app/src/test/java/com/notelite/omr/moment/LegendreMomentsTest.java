/*
 * To change this template, choose Tools | Templates
 * and open the template in the editor.
 */
package com.notelite.omr.moment;

import com.notelite.omr.moments.BasicLegendreExtractor;
import com.notelite.omr.moments.BasicLegendreMoments;
import com.notelite.omr.moments.LegendreMoments;

import org.junit.*;

/**
 *
 * @author Etiolles
 */
public class LegendreMomentsTest
        extends MomentsExtractorTest<LegendreMoments>
{
    /**
     * Creates a new LegendreMomentsTest object.
     */
    public LegendreMomentsTest ()
    {
    }

    /**
     * Test of generate method, of class LegendreMoments.
     */
    @Test
    public void testAllShapes ()
    {
        try {
            BasicLegendreExtractor instance = new BasicLegendreExtractor();
            super.testAllShapes(instance, BasicLegendreMoments.class);
        } catch (Exception ex) {
            ex.printStackTrace();
        }
    }
}
