\header {
  enteredby = 	"Allen Garvin"
  maintainer = 	"Allen Garvin"
  license = 	"Public Domain"
  filename = 	"anna-magdalena-04.ly"
  title = 	"Menuet in G"
  subtitle = 	"BWV Anh. 114"
  opus = 	"attributed to Christian Petzold (1677-1733)"
  composer =	"Johann Sebastian Bach (1685-1750)"
  style =	"Baroque"
  source =	"Bach-Gesellschaft"
  lastupdated =	"2010/Oct/30"

  mutopiainstrument = "Harpsichord, Piano, Clavichord"
  mutopiatitle =      "Menuet"
  mutopiacomposer =   "BachJS"
  mutopiaopus =       "BWV Anh. 114"
  mutopiadate =       "1725"
  mutopiamoreInfo =  "<p>A guitar arrangement and a trumpet duet transcription of this piece can both be found in the Mutopia archive.</p>"

 footer = "Mutopia-2017/01/19-75"
 copyright = \markup {\override #'(font-name . "DejaVu Sans, Bold") \override #'(baseline-skip . 0) \right-column {\with-url #"http://www.MutopiaProject.org" {\abs-fontsize #9  "Mutopia " \concat {\abs-fontsize #12 \with-color #white \char ##x01C0 \abs-fontsize #9 "Project "}}}\override #'(font-name . "DejaVu Sans, Bold") \override #'(baseline-skip . 0 ) \center-column {\abs-fontsize #11.9 \with-color #grey \bold {\char ##x01C0 \char ##x01C0 }}\override #'(font-name . "DejaVu Sans,sans-serif") \override #'(baseline-skip . 0) \column { \abs-fontsize #8 \concat {"Typeset using " \with-url #"http://www.lilypond.org" "LilyPond " "by " \maintainer " " \char ##x2014 " " \footer}\concat {\concat {\abs-fontsize #8 { "Placed in the " \with-url #"http://creativecommons.org/licenses/publicdomain" "public domain " "by the typesetter " \char ##x2014 " free to distribute, modify, and perform" }}\abs-fontsize #13 \with-color #white \char ##x01C0 }}}
 tagline = ##f
}
#(set-global-staff-size 21)
\pointAndClickOff

\version "2.19.49"

voiceone =  \relative c'' {
  \clef "treble"
  \time 3/4
  \key g \major

  \repeat "volta" 2 {
    d4  g,8[ a b c] |
    d4 g, g |
    e'  c8^[\mordent d e fis] |
    g4 g, g |
    c4^\mordent  d8[ c b a] | \break
    b4  c8[ b a g] |
    fis4  g8[ a b g] |
    \grace b8 a2. |
    d4  g,8[ a b c] |
    d4 g, g | \break
    e'4  c8[\mordent d e fis] |
    g4 g, g |
    c4\mordent  d8[ c b a] |
    b4  c8[ b a g] |
    a4  b8[ a g fis] |
    g2. | \break
  }
  \repeat "volta" 2 {
    b'4  g8[ a b g] |
    a4  d,8[ e fis d] |
    g4  e8[ fis g d] |
    cis4  b8[ cis] a4 |
    a8[ b cis d e fis] | \break
    g4 fis e |
    fis a, cis |
    d2. |
    d4  g,8[ fis] g4 |
    e'4  g,8[ fis] g4 | \break
    d'4 c b |
     a8[ g fis g] a4 |
     d,8[ e fis g a b] |
    c4 b^\prall a |
     b8[ d] g,4 fis |
    << { \stemUp g2. \stemNeutral }
      { \context Voice = "ii" { << \stemDown { <d b> } >> } }
    >> |
  }
}

voicetwo =  \relative c' {
  \clef "bass"
  \time 3/4
  \key g \major

  \repeat "volta" 2 {
    << { \stemUp { <b d>2 } \stemNeutral }
      { \context Voice = "ii" { << \stemDown g2 >> } }
    >> a4 |
%     <g b d>2 a4 |
    b2. |
    c2. |
    b2. |
    a2. |
    g2. |
    d'4 b g |
    d'  d,8[ c' b a] |
    b2 a4 |
    g b g |
    c2. |
    b4  c8[ b a g] |
    a2 fis4 |
    g2 b4 |
    c d d, |
    g2 g,4 |
  }
  \repeat "volta" 2 {
    g'2. |
    fis2. |
    e4 g e |
    a2 a,4 |
    a'2. |
    b4 d cis |
    d fis, a |
    d d, c'! |
    << { \stemUp { r4 d2 } \stemNeutral }
      { \context Voice = "ii" { << \stemDown { b2 b4 } >> } }
    >> |
    << { \stemUp { r4 e2 } \stemNeutral }
      { \context Voice = "ii" { << \stemDown { c2 c4 } >> } }
    >> |
    b4 a g |
    d'2 r4 |
    << { \stemUp { r4 r fis, } \stemNeutral }
      { \context Voice = "ii" { << \stemDown d2. >> } }
    >> |
    e4 g fis |
    g b, d |
    g d g, |
  }
}

\paper{
}
  
\score {
   \context GrandStaff << 
    \context Staff = "one" <<
      \voiceone
    >>
    \context Staff = "two" <<
      \voicetwo
    >>
  >>

  \layout{}
  
  \midi {
    \tempo 4 = 140
    }

}

