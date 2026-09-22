\version "2.10.25"

\header {
  title = "Sonate 16 in C major"
  subtitle = "Sonata facile"
  composer = "W. A. Mozart"
  opus = "K 545"
  piece = "Allegro"
  mutopiatitle = "Sonata Facile - First movement"
  mutopiacomposer = "MozartWA"
  mutopiainstrument = "Piano"
  style = "Classical"
  copyright = "Creative Commons Attribution-ShareAlike 3.0"
  source = "IMSLP"
  maintainer = "Alejandro Sierra"
  maintainerEmail = "algsierra@gmail.com"
 footer = "Mutopia-2007/07/22-998"
 tagline = \markup { \override #'(box-padding . 1.0) \override #'(baseline-skip . 2.7) \box \center-align { \small \line { Sheet music from \with-url #"http://www.MutopiaProject.org" \line { \teeny www. \hspace #-1.0 MutopiaProject \hspace #-1.0 \teeny .org \hspace #0.5 } • \hspace #0.5 \italic Free to download, with the \italic freedom to distribute, modify and perform. } \line { \small \line { Typeset using \with-url #"http://www.LilyPond.org" \line { \teeny www. \hspace #-1.0 LilyPond \hspace #-1.0 \teeny .org } by \maintainer \hspace #-1.0 . \hspace #0.5 Copyright © 2007. \hspace #0.5 Reference: \footer } } \line { \teeny \line { Licensed under the Creative Commons Attribution-ShareAlike 3.0 (Unported) License, for details see: \hspace #-0.5 \with-url #"http://creativecommons.org/licenses/by-sa/3.0" http://creativecommons.org/licenses/by-sa/3.0 } } } }
}
  
%{ Abreviations
  Suffixes rh = right hand
           lh = left hand
  Prefixes pt = principal theme
           st = secondary theme
           cl = close
           dv = development
           cd = coda
           mt = middle theme
%}

#(define afterGraceFraction (cons 15 16))

%%% Right Hand

ptrha = \relative c'' {  
  c2-1(\mp e4-3 g-5 
  b,4.-1_> c16 d c4) r4
  a'2-3(_\accent g4\< c\!
  g-3_\accent f8\trill\> e16 f e4)\! r4 % \break
  
  a,8\p\<\( b16 c d-1 e f g\!  a\> g f e d c-4 b a\! 
  g8\< a16 b c-1 d e f\!  g\> f e d c \tag #'first b-4 \tag #'second b-3 a g\!
  f8\< g16 a b-1 c d e\!  f\> e d c \tag #'first {b a-4 g f\!} \tag #'second {b-3 a g f-2\!}

  e8\< f16 g  a-1 b c d\!  e\> d c b a \tag #'first g-4 \tag #'second g-3 f e\!\)
}

ptrhb = \relative c'' {  
  b8->\f( g')  e-.-3 c-.-1  d-2( g)  e-. c-.
  d4-. <b d g>-. g-.-2 r4
}

ptrh = {
  \ptrha

  \relative c' {  
    d8\p\( e16 f  g-1 a b cis    d a\< b cis d-1 e f g\! 
    a b c! b  a g f-3 e  f g a g  f e d c!-2 \)
  }
  
  \ptrhb
}

strha = \relative c' {  
  r1
  d''8\mp( b) g4.( a16 b a8 g)
  \acciaccatura a8 g8.\trill-3( fis16-.-2) fis4-3 r2
  d'8\mp( b) g4.( a16 b a8 g)

  \acciaccatura a8 g8.\trill-3( fis16) fis4 r2
}

strhb = \relative c'' {  
  d'4->-5 r16 d16-5 b-4 g-2 e4-1 r16 e16(-1 g-2 e)
  c'4-> r16 c( a fis d4) 
}

strhc = \relative c'' {  
  r16 d16( fis d)
  % 20
  b'4->-5 r16 b( g e c4) r16 c( e c
  a'4->-5) r16 a-5( fis-4 d-2 b4)  r16 g'-5( d-3 b-2
}

strh = {
  \strha
  \strhb
  \strhc
  \relative c'' {  
    a2\p) \acciaccatura b8-2 c4-.-3\< \acciaccatura dis8-2 e4-.-3\!

    \acciaccatura { gis8-2 } a4.-> b32( a gis a c8-5 a-3) c( a)
    b-3(\f g-1) d'2-5(\sf c16 b a g)

    \phrasingSlurDown    
    \acciaccatura b8-3 \afterGrace a1 \startTrillSpan \( ( {g16 [ a ] )
							    \stopTrillSpan}
     g4\) g16-2( d g b-4 d-5 b-4 g b-4 c-5 a-3 fis-2 a-4
     g4-.) g,16-2( d g b-4 d_> b-4 g b-4 c-> a-3 fis-2 a-4
     g4-.) <d' b'>-. <b g'-4>-. r4
   }
}

dvrh = \relative c'' {  
  g4-. g'16-2( d g bes-3 d-5 bes-3 g bes c-5 a-3 fis-2 a-4
  g4-.) g,16-2_( d g bes-3 d bes-3 g bes  c-5 a-3 fis-2 a-4
  g4-.) r r16 g'-2 bes-4 a g f e-4 d 
  
  cis4-.\sf r r16 cis'-3( e d  cis bes a g-3 
  f4\sf)  d16-2( a-1 d f-4 a f-4 d-2 f g-5 e-3 cis-2 e-4
  d4-.) d,16-2 a d f-4  a f d-2 f  g-5 e-3 cis e

  r16 d-1( e f  g-1 a b cis d4-.\sf) r4
  r16 b-1( c d e-1 fis gis a b4-.\sf) r
  r16 a-1( e'-5 d c b a g f4-.\sf) r

  r16 g-1( d'-5 c b a g f-3 e4-.\sf) r
  r16 f-1( c'-5 b a g f e-3 d4-.\sf) r
  r16 e-1( b'-5 a gis f e d-3 c4-.\sf) r
  \break
  r16 bes-3 d c  bes a g f-3  e\> f-1 g a  bes c-1 d e\!
}

ptirh = \relative c'' {
  a'4-. r r <c, a'-5>-.
  <c g'-4>-. r r <c g'-5>-.
  <c f-4>-. r r <b f'-5>-.
  <c-2 e-4>-. r r <c e>-.

  d16-5\( d, e f  g a b cis  d a-1 b cis  d-1 e f g-1
  a b c b  a g f e  f g a g  f e d c-2\)

  \ptrhb
}

stvrh = {
  \transpose c f, { \strhb } 
  \transpose d g { 
    \strhc
     \relative c'' {  
       a2\p) \acciaccatura gis8-2 a4-. \acciaccatura gis8 a4-.
     }
  } 
  \relative c''' {  
    a2\p \acciaccatura gis8-2 a4-. \acciaccatura gis8 a4-.
    
    g8-1\f( a16 b c-1 d e d c b-4 a g  f e-3d c)

    \phrasingSlurDown
    \acciaccatura e8-3 \afterGrace d1 \startTrillSpan \( ({c16[ d])
							   \stopTrillSpan}
    \phrasingSlurUp
    c4-.\) c16-2\( g_> c e-4  g e-4 c e-4  f_> d-3 b d-3 c4-.
    c,16-2 g-> c e-4  g e-4 c e-4  f-> d-3 b d-3\)
    c4-. <e'-1 g-2 c-5>-. c-2 r 

  }
}


%%% Left Hand

ptlha = \relative c'' {  
  c,8-5(\p g'-1 e-3 g  c,  g' e g)
  d-4 g-1 f-2 g  c,-5 g'-1 e-3 g
  c, a'-1 f-2 a  c, g'-1 e-3 g
  b,-5 g'-1 d-3 g  c,-4 g'-1 e-2 g
  
  f4 r4 r4 \clef bass <f, c'>_4-.
  <e c'>-. r4 r4 <e c'>_4-.
  <d c'>-. r4 r4 <d b'>_4-.  
}

ptlhb = \relative c' {  
  g,16-5\( b-4 d-2 g  g,-5 c-3 e-2 g  g, b d g  g, c e g  
  g,4-.\) g'-. g,-. r
}

ptlh = {
  \ptlha
  \relative c {  
    <c c'>-. r4 r4 <c-5 e-3>-.
    <f-2 a-1>1
    f4._3( g8 a4. fis8_2)
  }
  \ptlhb
}

stlha = \relative c {  
  cis'16->\p-2( d cis d  cis d cis d  c_2-> d c d  c d c d)

  b->_3 d b d \repeat unfold 3 { b d b d }
  c-2\mp d b-3 d  a-4 d b-3 d  c d b d  c d a d
  \repeat unfold 4 { b d b d }

  c d b d  a d b d  c d b d  c d a d
}

stlhb = \relative c' {  
  \clef treble r16 b-5( d-4 g-2 b4) r16 c,-5( e-4 g-2 c4)
  r16 a,-5( c-4 fis-2 a4) r16 b,-5( d-4 fis-2 b4)
}

stlhc = \relative c' {  
  % 20
  r16 g-5( b-4 e-2 g4) r16 a,-5( c-4 e-2 a4)
  r16 fis,-5( a-4 d-2 fis4) r16 g,-5( b-4 d-2 g4)
}

stlh = {
  \stlha
  \stlhb
  \stlhc
  \relative c' {
    \clef treble \repeat unfold 16 <c e>8-.

    d16_5 b'_1 g_2 b \repeat unfold 3 { d, b' g b } 
    \repeat unfold 4 { d, c' fis, c' }

    <g-2 b-1>4 r r <a c d,>
    <g-2 b-1> r r \clef bass <d, a' c>
    <g b> <g g,> <g g,> r  
  }
}

dvlha = \relative c' { r16 g_5( a bes  c d e-3 fis g4-.\sf) r }

dvlh = \relative c {
  <g g'>4 r r \clef treble <d'' a' c>(
  <g-3 bes-1>) r r \clef bass <d, a' c>
  \dvlha
  \transpose c d \dvlha
  <d, d'>4 r r \clef treble <a'' e' g>(
  <d-3 f-1>4-.) r r \clef bass <a, e' g>(

  <d_5 f_4>4-.) r r16 d'-3( f e d c-1 b a
  gis4-.)\sf r r16 gis-3( b a g f-1 e d
  c4-.)\sf r \clef treble r16 d'-5( a'-1 g f e-1 d c
  \break

  b4-.\sf) r r16 c-5( g' f  e d-1 c b 
  a4-.\sf) r r16 b-5( f' e  d c-1 b a
  \clef bass gis4-.\sf) r r16 a-3( c-1 b  a g-1 f e
  
  d2\sf) <c g' bes>\sf
}
  
%ptilha = \relative c {
%  f8-5 g16 a  bes c d-3 e f e d-1 c  bes a-1 g f
%}

ptilh = \relative c {
  <f f'>4-. r4 r2
  f8-5\( g16 a  bes c d-3 e f e d-1 c  bes a-1 g f  % \ptilha
  e8 f16 g  a b-4 c d  e d c b  a-1 g f e
  d8 e16 f  g a b-3 c  d c b a  g-1 f e d
  \transpose f c {   f8-5 g16 a  bes c d-3 e f e d-1 c  bes a-1 g f } % \ptilha }
  
  \once \set fingeringOrientations = #'(right)
  <f-2 a-1>1\p\) 
  f4.-3 g8 a4. fis8-2

  \ptlhb
}

stvlh = {
  \transpose c f, { \stlhb } 
  \transpose d g { \stlhc } 
  \relative c' {  
    r8 \repeat unfold 7 { <f a>8-. }
    \clef bass \repeat unfold 8 { <fis, c' ees>8-. }
    \repeat unfold 4 { g16-5 e' c-2 e }
    \repeat unfold 4 { g,16 f' b, f' }
    <c-2 e-1>4-. r r <g  d' f>(
    \slurDown
    <c_3 e_1>-.) r r <g, d' f>(
    <c e>) <c c'>-. <c c,> r
  }
}


\score {
  \new PianoStaff <<
    \new Staff { 
      \override Fingering #'avoid-slur = #'inside
      \keepWithTag #'first
      \repeat volta 2 { \ptrh \strh } \break 
      \repeat volta 2 {
	\dvrh 
	\phrasingSlurUp
	\keepWithTag #'second
	\transpose c f { \ptrha }
	\ptirh
	\transpose d g, { \strha }
	\stvrh
      }
    }
    \new Staff { 
      \override Fingering #'avoid-slur = #'inside
      \repeat volta 2 { \ptlh \stlh } 
      \repeat volta 2 {
	\dvlh 
	\clef treble \transpose c f { \ptlha }
	\ptilh
	\clef treble \transpose c f { \stlha }	
	\stvlh
      }
    }
  >>
  \layout {}
  \midi {
    \context {
      \Score
      tempoWholesPerMinute = #(ly:make-moment 132 4)
    }
  }
}
