import { DOMParser as XMLDOMParser, XMLSerializer as XMLDOMSerializer } from "@xmldom/xmldom";

/** Real XML DOM for Node-only tests; reject parser recovery like browser XML. */
class StrictXMLDOMParser extends XMLDOMParser {
  constructor() { super({ onError: (_level, message) => { throw new Error(message); } }); }
}
Object.assign(globalThis, { DOMParser: StrictXMLDOMParser, XMLSerializer: XMLDOMSerializer });

export const noteXML = (duration = 1, options = "", pitch = "C", type = "quarter") => `<note>${options}<pitch><step>${pitch}</step><octave>4</octave></pitch><duration>${duration}</duration><voice>1</voice><type>${type}</type></note>`;
export const attributesXML = (divisions = 1, beats = "4", beatType = 4) => `<attributes><divisions>${divisions}</divisions><time><beats>${beats}</beats><beat-type>${beatType}</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>`;
export const scoreXML = (measures: string, partId = "P1") => `<score-partwise version="4.0"><part-list><score-part id="${partId}"><part-name>Piano</part-name><score-instrument id="${partId}-I1"><instrument-name>Piano</instrument-name></score-instrument></score-part></part-list><part id="${partId}">${measures}</part></score-partwise>`;
