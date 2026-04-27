/*
 * To change this template, choose Tools | Templates
 * and open the template in the editor.
 */
package com.notelite.omr.moment;

import com.notelite.omr.moments.ARTMoments;
import com.notelite.omr.moments.BasicARTExtractor;
import com.notelite.omr.moments.BasicARTMoments;

import org.junit.*;

/**
 * Unit test for (Basic) ARTExtractor.
 *
 * @author NoteLite Contributors
 */
public class ARTExtractorTest
        extends MomentsExtractorTest<ARTMoments>
{
    /**
     * Creates a new ARTExtractorTest object.
     */
    public ARTExtractorTest ()
    {
    }

    /**
     * Test of generate method, of class ARTMoments.
     */
    @Test
    public void testAllShapes ()
            throws Exception
    {
        super.testAllShapes(new BasicARTExtractor(), BasicARTMoments.class);
    }
}
