/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Bounded strict JSON at the local HTTP/process boundary, without optional UI dependencies. */
final class PracticeJson {
    private final String text;
    private int position;
    private PracticeJson(String text) { this.text = text; }
    static Object parse(String text) {
        PracticeJson parser = new PracticeJson(text);
        Object value = parser.value(0); parser.space();
        if (parser.position != text.length()) parser.fail();
        return value;
    }
    @SuppressWarnings("unchecked") static Map<String,Object> object(Object value) {
        if (!(value instanceof Map<?,?>)) throw new IllegalArgumentException("需要 JSON 对象。");
        return (Map<String,Object>) value;
    }
    static String stringify(Object value) {
        StringBuilder out = new StringBuilder(); write(value, out); return out.toString();
    }
    private static void write(Object value, StringBuilder out) {
        if (value == null) { out.append("null"); return; }
        if (value instanceof String string) {
            out.append('"');
            for (char c : string.toCharArray()) {
                switch(c) {
                    case '"', '\\' -> out.append('\\').append(c);
                    case '\n' -> out.append("\\n"); case '\r' -> out.append("\\r"); case '\t' -> out.append("\\t");
                    default -> { if (c < 32) out.append(String.format("\\u%04x", (int)c)); else out.append(c); }
                }
            }
            out.append('"'); return;
        }
        if (value instanceof Boolean) { out.append(value); return; }
        if (value instanceof Number number) { out.append(Double.isFinite(number.doubleValue()) ? number : "null"); return; }
        if (value instanceof Map<?,?> map) {
            out.append('{'); boolean first=true;
            for (var item : map.entrySet()) { if(!first)out.append(','); first=false; write(String.valueOf(item.getKey()),out); out.append(':'); write(item.getValue(),out); }
            out.append('}'); return;
        }
        if (value instanceof Iterable<?> items) {
            out.append('['); boolean first=true;
            for(Object item:items){if(!first)out.append(',');first=false;write(item,out);} out.append(']');return;
        }
        throw new IllegalArgumentException("不支持的 JSON 值："+value.getClass());
    }
    private void space(){while(position<text.length()&&" \r\n\t".indexOf(text.charAt(position))>=0)position++;}
    private boolean take(char c){space();if(position<text.length()&&text.charAt(position)==c){position++;return true;}return false;}
    private void need(char c){if(!take(c))fail();}
    private Object value(int depth){
        space();if(depth>32||position>=text.length())fail();char c=text.charAt(position);
        if(c=='"')return string();
        if(take('{')){Map<String,Object> values=new LinkedHashMap<>();if(take('}'))return values;
            do{String key=string();need(':');if(values.containsKey(key))fail();values.put(key,value(depth+1));}while(take(','));need('}');return values;}
        if(take('[')){List<Object> values=new ArrayList<>();if(take(']'))return values;
            do{values.add(value(depth+1));if(values.size()>100000)fail();}while(take(','));need(']');return values;}
        for(String literal:List.of("null","true","false"))if(text.startsWith(literal,position)){position+=literal.length();return literal.equals("null")?null:Boolean.valueOf(literal);}
        int start=position;if(c=='-')position++;
        if(position>=text.length()||text.charAt(position)<'0'||text.charAt(position)>'9')fail();
        if(text.charAt(position)=='0')position++;else while(position<text.length()&&Character.isDigit(text.charAt(position)))position++;
        if(position<text.length()&&text.charAt(position)=='.'){position++;int digits=position;while(position<text.length()&&Character.isDigit(text.charAt(position)))position++;if(digits==position)fail();}
        if(position<text.length()&&"eE".indexOf(text.charAt(position))>=0){position++;if(position<text.length()&&"+-".indexOf(text.charAt(position))>=0)position++;int digits=position;while(position<text.length()&&Character.isDigit(text.charAt(position)))position++;if(digits==position)fail();}
        double number=Double.parseDouble(text.substring(start,position));if(!Double.isFinite(number))fail();return number;
    }
    private String string(){need('"');StringBuilder value=new StringBuilder();
        while(position<text.length()){char c=text.charAt(position++);if(c=='"')return value.toString();if(c<32)fail();
            if(c=='\\'){if(position>=text.length())fail();c=text.charAt(position++);switch(c){
                case '"','\\','/'->value.append(c);case 'b'->value.append('\b');case 'f'->value.append('\f');case 'n'->value.append('\n');case 'r'->value.append('\r');case 't'->value.append('\t');
                case 'u'->{if(position+4>text.length())fail();value.append((char)Integer.parseInt(text.substring(position,position+4),16));position+=4;}default->fail();}
            }else value.append(c);}
        fail();return null;
    }
    private void fail(){throw new IllegalArgumentException("JSON 格式无效，位置 "+position);}
}
