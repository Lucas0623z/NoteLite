@XmlJavaTypeAdapters({ @XmlJavaTypeAdapter(value = Jaxb.PointAdapter.class, type = Point.class),
        @XmlJavaTypeAdapter(value = Jaxb.RectangleAdapter.class, type = Rectangle.class) })
package com.notelite.omr.jaxb.facade;

import com.notelite.omr.util.Jaxb;

import java.awt.Point;
import java.awt.Rectangle;

import javax.xml.bind.annotation.adapters.XmlJavaTypeAdapter;
import javax.xml.bind.annotation.adapters.XmlJavaTypeAdapters;
