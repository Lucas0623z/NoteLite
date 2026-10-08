#ifndef BASICPITCHCALCULATION_HPP
#define BASICPITCHCALCULATION_HPP

#include<iostream>
#include<fstream>
#include<string>
#include<sstream>
#include<vector>
#include<stdio.h>
#include<stdlib.h>
#include<cmath>
#include<cassert>
#include<algorithm>
using namespace std;

inline string OldSitchToSitch(string sitch_old){
	for(int i=0;i<sitch_old.size();i+=1){
		if(sitch_old[i]=='+'){sitch_old[i]='#';}
		if(sitch_old[i]=='-'){sitch_old[i]='b';}
	}//endfor i
	return sitch_old;
}//end OldSitchToSitch

inline string SitchToOldSitch(string sitch){
	for(int i=0;i<sitch.size();i+=1){
		if(sitch[i]=='#'){sitch[i]='+';}
		if(sitch[i]=='b'){sitch[i]='-';}
	}//endfor i
	return sitch;
}//end SitchToOldSitch

inline string PitchToSitch(int p){//pithc to spelled pitch (sitch)
	if(p<0){return "R";}//old rest
	int q=(p+120)%12;
	string qstr;
	stringstream ss;
	switch(q){
		case 0 : qstr="C"; break;
		case 1 : qstr="C#"; break;
		case 2 : qstr="D"; break;
		case 3 : qstr="Eb"; break;
		case 4 : qstr="E"; break;
		case 5 : qstr="F"; break;
		case 6 : qstr="F#"; break;
		case 7 : qstr="G"; break;
		case 8 : qstr="G#"; break;
		case 9 : qstr="A"; break;
		case 10 : qstr="Bb"; break;
		case 11 : qstr="B"; break;
	}//endswitch
	ss.str(""); ss<<qstr<<(p/12-1);
	return ss.str();
}//end PitchToSitch

inline string PitchToOldSitch(int p){//pithc to spelled pitch (sitch)
	int q=(p+120)%12;
	string qstr;
	stringstream ss;
	switch(q){
		case 0 : qstr="C"; break;
		case 1 : qstr="C+"; break;
		case 2 : qstr="D"; break;
		case 3 : qstr="E-"; break;
		case 4 : qstr="E"; break;
		case 5 : qstr="F"; break;
		case 6 : qstr="F+"; break;
		case 7 : qstr="G"; break;
		case 8 : qstr="G+"; break;
		case 9 : qstr="A"; break;
		case 10 : qstr="B-"; break;
		case 11 : qstr="B"; break;
	}//endswitch
	ss.str(""); ss<<qstr<<(p/12-1);
	return ss.str();
}//end PitchToOldSitch

inline int SitchToPitch(string sitch){
	if(sitch=="R"){return -1;}
	if(sitch=="rest"){return -1;}
	int p_rel,p;
	if(sitch[0]=='C'){p_rel=60;
	}else if(sitch[0]=='D'){p_rel=62;
	}else if(sitch[0]=='E'){p_rel=64;
	}else if(sitch[0]=='F'){p_rel=65;
	}else if(sitch[0]=='G'){p_rel=67;
	}else if(sitch[0]=='A'){p_rel=69;
	}else if(sitch[0]=='B'){p_rel=71;
	}//endif
	sitch.erase(sitch.begin());
	int oct=sitch[sitch.size()-1]-'0';
	sitch.erase(sitch.end()-1);
	p=p_rel+(oct-4)*12;
	if(sitch==""){p+=0;
	}else if(sitch=="#"){p+=1;
	}else if(sitch=="##"){p+=2;
	}else if(sitch=="b"){p-=1;
	}else if(sitch=="bb"){p-=2;
	}else if(sitch=="+"){p+=1;
	}else if(sitch=="++"){p+=2;
	}else if(sitch=="-"){p-=1;
	}else if(sitch=="--"){p-=2;
	}//endif
	return p;
}//end

inline int SitchClassToPitchClass(string sitch){
	int p_rel,p;
	if(sitch[0]=='C'){p_rel=0;
	}else if(sitch[0]=='D'){p_rel=2;
	}else if(sitch[0]=='E'){p_rel=4;
	}else if(sitch[0]=='F'){p_rel=5;
	}else if(sitch[0]=='G'){p_rel=7;
	}else if(sitch[0]=='A'){p_rel=9;
	}else if(sitch[0]=='B'){p_rel=11;
	}//endif
	sitch.erase(sitch.begin());
	p=p_rel+12;
	if(sitch==""){p+=0;
	}else if(sitch=="#"){p+=1;
	}else if(sitch=="##"){p+=2;
	}else if(sitch=="b"){p-=1;
	}else if(sitch=="bb"){p-=2;
	}else if(sitch=="+"){p+=1;
	}else if(sitch=="++"){p+=2;
	}else if(sitch=="-"){p-=1;
	}else if(sitch=="--"){p-=2;
	}//endif
	return p%12;
}//end

inline string PitchClassToSitchClass(int pc){
	int q=(pc+120)%12;
	string qstr;
	switch(q){
		case 0 : qstr="C"; break;
		case 1 : qstr="C#"; break;
		case 2 : qstr="D"; break;
		case 3 : qstr="Eb"; break;
		case 4 : qstr="E"; break;
		case 5 : qstr="F"; break;
		case 6 : qstr="F#"; break;
		case 7 : qstr="G"; break;
		case 8 : qstr="Ab"; break;
		case 9 : qstr="A"; break;
		case 10 : qstr="Bb"; break;
		case 11 : qstr="B"; break;
	}//endswitch
	return qstr;
}//end PitchClassToSitchClass

inline string PitchClassToOldSitchClass(int pc){
	int q=(pc+120)%12;
	string qstr;
	switch(q){
		case 0 : qstr="C"; break;
		case 1 : qstr="C+"; break;
		case 2 : qstr="D"; break;
		case 3 : qstr="E-"; break;
		case 4 : qstr="E"; break;
		case 5 : qstr="F"; break;
		case 6 : qstr="F+"; break;
		case 7 : qstr="G"; break;
		case 8 : qstr="A-"; break;
		case 9 : qstr="A"; break;
		case 10 : qstr="B-"; break;
		case 11 : qstr="B"; break;
	}//endswitch
	return qstr;
}//end PitchClassToOldSitchClass

inline int SitchToSitchHeight(string sitch){
	int oct=sitch[sitch.size()-1]-'0';
	char sitchClass=sitch[0];
	int ht;
	if(sitchClass=='C'){ht=0;
	}else if(sitchClass=='D'){ht=1;
	}else if(sitchClass=='E'){ht=2;
	}else if(sitchClass=='F'){ht=3;
	}else if(sitchClass=='G'){ht=4;
	}else if(sitchClass=='A'){ht=5;
	}else if(sitchClass=='B'){ht=6;
	}else{ht=0;
	}//endif
	return ht+7*(oct-4);
}//end SitchToSitchHeight

inline int SitchToAcc(string sitch){
	string accLab=sitch.substr(1,sitch.size()-2);
	if(accLab==""){return 0;
	}else if(accLab=="#"){return 1;
	}else if(accLab=="##"){return 2;
	}else if(accLab=="b"){return -1;
	}else if(accLab=="bb"){return -2;
	}else if(accLab=="+"){return 1;
	}else if(accLab=="++"){return 2;
	}else if(accLab=="-"){return -1;
	}else if(accLab=="--"){return -2;
	}else{return 0;
	}//endif
}//end SitchToAcc

inline int SitchToPytchClass(string sitch){
	int pytch;
	if(sitch[0]=='F'){pytch=-1;
	}else if(sitch[0]=='C'){pytch=0;
	}else if(sitch[0]=='G'){pytch=1;
	}else if(sitch[0]=='D'){pytch=2;
	}else if(sitch[0]=='A'){pytch=3;
	}else if(sitch[0]=='E'){pytch=4;
	}else if(sitch[0]=='B'){pytch=5;
	}else{pytch=-100;//rest R
	}//endif
	pytch+=SitchToAcc(sitch)*7;
	return pytch;
}//end SitchToPytchClass

inline int SitchClassToPytchClass(string sitch){
	sitch+="4";
	return SitchToPytchClass(sitch);
}//end SitchToPytchClass

inline string PytchClassToSitchClass(int pytch){
	string sitchClass="";
	sitchClass=PitchClassToSitchClass( (((pytch+1+700)%7-1)*7+120)%12 );
	if(pytch>=13){
		sitchClass+="##";
	}else if(pytch>=6){
		sitchClass+="#";
	}else if(pytch<=-9){
		sitchClass+="bb";
	}else if(pytch<=-2){
		sitchClass+="b";
	}//endif
	return sitchClass;
}//end PytchClassToSitchClass

inline string TransposeFifthSitch(string sitch, int keyfifthShift){
	if(sitch=="R"){return sitch;}
	int pitchShift = (keyfifthShift*7+1200)%12;
	//new pitch = prev pich + pitchShift
	int pitch=SitchToPitch(sitch);
	pitch+=pitchShift;
	int oct=sitch[sitch.size()-1]-'0';
	sitch.erase(sitch.end()-1);
	sitch=PytchClassToSitchClass(SitchClassToPytchClass(sitch)+keyfifthShift);
	stringstream ss;
	ss.str(""); ss<<oct;
	int tmpPitch=SitchToPitch(sitch+ss.str());
	oct+=(pitch-tmpPitch)/12;
	ss.str(""); ss<<oct;
	sitch+=ss.str();
	return sitch;
}//end TransposeFifthSitch

inline string KeyFromKeySignature(int key_fifth,string key_mode){
	string key="Cmaj";
	if(key_mode=="major" && key_fifth==-7){key="Cbmaj";
	}else if(key_mode=="major" && key_fifth==-6){key="Gbmaj";
	}else if(key_mode=="major" && key_fifth==-5){key="Dbmaj";
	}else if(key_mode=="major" && key_fifth==-4){key="Abmaj";
	}else if(key_mode=="major" && key_fifth==-3){key="Ebmaj";
	}else if(key_mode=="major" && key_fifth==-2){key="Bbmaj";
	}else if(key_mode=="major" && key_fifth==-1){key="Fmaj";
	}else if(key_mode=="major" && key_fifth==0){key="Cmaj";
	}else if(key_mode=="major" && key_fifth==1){key="Gmaj";
	}else if(key_mode=="major" && key_fifth==2){key="Dmaj";
	}else if(key_mode=="major" && key_fifth==3){key="Amaj";
	}else if(key_mode=="major" && key_fifth==4){key="Emaj";
	}else if(key_mode=="major" && key_fifth==5){key="Bmaj";
	}else if(key_mode=="major" && key_fifth==6){key="F#maj";
	}else if(key_mode=="major" && key_fifth==7){key="C#maj";
	}else if(key_mode=="minor" && key_fifth==-7){key="Abmin";
	}else if(key_mode=="minor" && key_fifth==-6){key="Ebmin";
	}else if(key_mode=="minor" && key_fifth==-5){key="Bbmin";
	}else if(key_mode=="minor" && key_fifth==-4){key="Fmin";
	}else if(key_mode=="minor" && key_fifth==-3){key="Cmin";
	}else if(key_mode=="minor" && key_fifth==-2){key="Gmin";
	}else if(key_mode=="minor" && key_fifth==-1){key="Dmin";
	}else if(key_mode=="minor" && key_fifth==0){key="Amin";
	}else if(key_mode=="minor" && key_fifth==1){key="Emin";
	}else if(key_mode=="minor" && key_fifth==2){key="Bmin";
	}else if(key_mode=="minor" && key_fifth==3){key="F#min";
	}else if(key_mode=="minor" && key_fifth==4){key="C#min";
	}else if(key_mode=="minor" && key_fifth==5){key="G#min";
	}else if(key_mode=="minor" && key_fifth==6){key="D#min";
	}else if(key_mode=="minor" && key_fifth==7){key="A#min";
	}//endif
	return key;
}//end KeyFromKeySignature

inline int PitchAboveDiagonic(int pitch,int key_fifth){
	int ret=pitch+2;
	int found=-1;
	for(int i=-1;i<=5;i++){
		if( (7*(key_fifth+i)+1200)%12==ret%12 ){found=0;break;}
	}//endfor i
	if(found<0){ret=pitch+1;}
	return ret;
}//end PitchAboveDiagonic

inline int PitchBelowDiagonic(int pitch,int key_fifth){
	int ret=pitch-2;
	int found=-1;
	for(int i=-1;i<=5;i++){
		if( (7*(key_fifth+i)+1200)%12==ret%12 ){found=0;break;}
	}//endfor i
	if(found<0){ret=pitch-1;}
	return ret;
}//end PitchBelowDiagonic

class ChordSymbol{
public:
	string fullname;//C#m7/E
	string root;//C#
	string form;//m7
	string bass;//E
	vector<int> pcset;
	vector<int> pcsetOrdered;

	ChordSymbol(){
	}//end ChordSymbol
	ChordSymbol(string fullname_){
		fullname=fullname_;
		InitFromFullname();
	}//end ChordSymbol
	~ChordSymbol(){
	}//end ~ChordSymbol

	void InitFromFullname(){
		string str=fullname;
		stringstream ss;
		if(fullname=="NC"){
			root="R";
			form="NC";
			bass="R";
		}else if(fullname.size()==1){
			root=fullname;
			form="";
			bass=root;
		}else{
			if(fullname[1]=='#' || fullname[1]=='b'){
				ss.str(""); ss<<fullname[0]<<fullname[1];
				root=ss.str();
				str=fullname.substr(2);
			}else{
				ss.str(""); ss<<fullname[0];
				root=ss.str();
				str=fullname.substr(1);
			}//endif
			if(str.find("/")==string::npos){
				form=str;
				bass=root;
			}else{
				form=str.substr(0,str.find("/"));
				bass=str.substr(str.find("/")+1);
			}//endif
		}//endif

		//Normalize notation
		if(form=="maj7" || form=="Maj7"){
			form="M7"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="(7)"){
			form="7"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="mmaj7" || form=="min(maj7)" || form=="m(Maj7)"){
			form="mM7"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="sus47" || form=="sus4(add7)" || form=="7sus4(add7)"){
			form="7sus4"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m7(b5)(addb5)"  || form=="m7-5"){
			form="m7(b5)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="9sus(add9)"){
			form="sus4(add9)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m7(add7)"){
			form="m7"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m7sus4(add7)"){
			form="m7sus4"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="7(b9)"){
			form="7(addb9)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="(add2)"){
			form="(add9)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m(add2)"){
			form="m(add9)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m(9)"){
			form="m9"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="(11)"){
			form="11"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="m(11)"){
			form="m11"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="69(add9)"){
			form="6(add9)"; if(bass==root){fullname=root+form;}else{fullname=root+form+"/"+bass;}//endif
		}else if(form=="N.C." || form=="(N.C.)"){
			form="NC"; fullname="NC"; root="R"; bass="R";
		}//endif

//cout<<"fullname,root,form,bass:\t"<<fullname<<"\t"<<root<<"\t"<<form<<"\t"<<bass<<endl;
		SetPcset();
	}//end InitFromFullname

	void WriteFullname(){
		if(root=="R"){fullname="NC"; return;}
		stringstream ss;
		ss.str(""); ss<<root<<form;
		if(bass!=root){
			ss<<"/"<<bass;
		}//endif
		fullname=ss.str();
	}//end WriteFullname

	void Transpose(int tonicTo){//new tonic = prev toni + tonicTo
		if(tonicTo==0 || root=="R"){return;}
		int newRootPC=(SitchClassToPitchClass(root)+tonicTo+120)%12;
		int newBassPC=(SitchClassToPitchClass(bass)+tonicTo+120)%12;
		root=PitchClassToSitchClass(newRootPC);
		bass=PitchClassToSitchClass(newBassPC);
		WriteFullname();
	}//end Transpose

	void TransposeFifth(int degreeDiff){//new degree = prev degree + degreeDiff
		if(degreeDiff==0 || root=="R"){return;}
		root=PytchClassToSitchClass(SitchClassToPytchClass(root)+degreeDiff);
		bass=PytchClassToSitchClass(SitchClassToPytchClass(bass)+degreeDiff);
		WriteFullname();
	}//end TransposeFifth

	vector<int> FormToPcset(string form_){
		vector<int> vi;
		if(form_=="NC"){

		}else if(form_==""){
			vi.push_back(0); vi.push_back(4); vi.push_back(7);
		}else if(form_=="m"){
			vi.push_back(0); vi.push_back(3); vi.push_back(7);
		}else if(form_=="7"){
			vi.push_back(0); vi.push_back(4); vi.push_back(7); vi.push_back(10);
		}else if(form_=="dim"){
			vi.push_back(0); vi.push_back(3); vi.push_back(6);
		}else if(form_=="aug"){
			vi.push_back(0); vi.push_back(4); vi.push_back(8);
		}else if(form_=="M7"){
			vi.push_back(0); vi.push_back(4); vi.push_back(7); vi.push_back(11);
		}else if(form_=="m7"){
			vi.push_back(0); vi.push_back(3); vi.push_back(7); vi.push_back(10);
		}else if(form_=="mM7"){
			vi.push_back(0); vi.push_back(3); vi.push_back(7); vi.push_back(11);
		}else if(form_=="m7(b5)"){//=half-diminished, tristan chord
			vi.push_back(0); vi.push_back(3); vi.push_back(6); vi.push_back(10);
		}else if(form_=="aug7"){
			vi.push_back(0); vi.push_back(4); vi.push_back(8); vi.push_back(11);
		}else if(form_=="dim7"){
			vi.push_back(0); vi.push_back(3); vi.push_back(6); vi.push_back(9);
		}else if(form_=="sus4"){
			vi.push_back(0); vi.push_back(5); vi.push_back(7);
		}else if(form_=="6"){
			vi.push_back(0); vi.push_back(4); vi.push_back(7); vi.push_back(9);
		}else if(form_=="9"){
			vi.push_back(0); vi.push_back(2); vi.push_back(4); vi.push_back(7); vi.push_back(10);
		}else if(form_=="M9"){
			vi.push_back(0); vi.push_back(2); vi.push_back(4); vi.push_back(7); vi.push_back(11);
		}else if(form_=="m9"){
			vi.push_back(0); vi.push_back(2); vi.push_back(3); vi.push_back(7); vi.push_back(10);
		}else if(form_=="(add9)"){
			vi.push_back(0); vi.push_back(2); vi.push_back(4); vi.push_back(7);
		}else if(form_=="7sus4" || form_=="sus47"){
			vi.push_back(0); vi.push_back(5); vi.push_back(7); vi.push_back(10);
		}else{
			vi.push_back(0);
		}//endif
		return vi;
	}//end FormToPcset

	void SetPcset(){
		pcset=FormToPcset(form);
		if(fullname=="NC"){pcset.clear(); pcsetOrdered.clear(); return;}
		int rootPitch=SitchClassToPitchClass(root);
		for(int k=0;k<pcset.size();k+=1){
			pcset[k]=(pcset[k]+rootPitch)%12;
		}//endfor k
		pcsetOrdered=pcset;
		sort(pcset.begin(),pcset.end());
	}//end SetPcset

	void CheckKnownChordType(){
		if(form=="" || form=="m" || form=="dim" || form=="aug"){
		}else if(form=="7" || form=="M7" || form=="m7" || form=="dim7" || form=="aug7" || form=="mM7" || form=="m7(b5)"){
		}else if(form=="9" || form=="m9" || form=="M9" || form=="6" || form=="m6" || form=="sus4" || form=="7sus4" || form=="11" || form=="m11"){
		}else if(form=="13" || form=="7(b5)" || form=="m13" || form=="6(add9)" || form=="sus4(add9)" || form=="aug9"){
		}else if(form=="7(addb9)" || form=="aug9" || form=="(add9)" || form=="sus2" || form=="9(b5)" || form=="9(#5)"){
		}else if(form=="m(#5)" || form=="7(add#9)" || form=="7(add#11)" || form=="7(#5)" || form=="7(addb13)" || form=="9(add#11)"){
		}else if(form=="NC" || form=="M7(#5)" || form=="13(b9)" || form=="m7(add11)" || form=="M7(add#11)" || form=="m7(#5)"){
		}else if(form=="M7(b5)" || form=="M13" || form=="13(b5)" || form=="m9(b5)" || form=="sus4(add13)" || form=="M9(add#11)"){
		}else if(form=="(omit3)" || form=="m(add9)" || form=="7(add13)" || form=="7(add11)" || form=="(b5)" || form=="m7sus4"){
//		}else if(form=="" || form=="" || form=="" || form=="" || form=="" || form==""){
		}else{
cout<<"Unknown chord type:\t"<<form<<"\t"<<fullname<<endl;
		}//endif
	}//endif

};//endclass ChordSymbol


//Abc
inline string PitchToAbcPitch(int pitch){
	if(pitch<0){return "z";}
	stringstream ss;
	int pc=pitch%12;
	int oct=pitch/12-1;
	if(oct>=5){
		if(pc==0){ss<<"=c";
		}else if(pc==1){ss<<"^c";
		}else if(pc==2){ss<<"=d";
		}else if(pc==3){ss<<"_e";
		}else if(pc==4){ss<<"=e";
		}else if(pc==5){ss<<"=f";
		}else if(pc==6){ss<<"^f";
		}else if(pc==7){ss<<"=g";
		}else if(pc==8){ss<<"^g";
		}else if(pc==9){ss<<"=a";
		}else if(pc==10){ss<<"_b";
		}else if(pc==11){ss<<"=b";
		}//endif
		for(int i=6;i<=oct;i+=1){ss<<"'";}
	}else{
		if(pc==0){ss<<"=C";
		}else if(pc==1){ss<<"^C";
		}else if(pc==2){ss<<"=D";
		}else if(pc==3){ss<<"_E";
		}else if(pc==4){ss<<"=E";
		}else if(pc==5){ss<<"=F";
		}else if(pc==6){ss<<"^F";
		}else if(pc==7){ss<<"=G";
		}else if(pc==8){ss<<"^G";
		}else if(pc==9){ss<<"=A";
		}else if(pc==10){ss<<"_B";
		}else if(pc==11){ss<<"=B";
		}//endif
		for(int i=3;i>=oct;i-=1){ss<<",";}
	}//endif
	return ss.str();
}//end PitchToAbcPitch

inline string GetAbcNote(vector<int> pitches, int nv){
	//nv%48=1/5/7/10/11/13/17/19/22/23 are forbidden!!
	string abcPitch = "";
	for (int i = 0; i < pitches.size(); i++) {
		abcPitch += PitchToAbcPitch(pitches[i]);
	}
	if (pitches.size() > 1){ abcPitch = "[" + abcPitch + "]";}
	stringstream ss;
	ss << abcPitch << nv;
	return ss.str();
	// while(nv>48){
	// 	ss<<abcPitch<<"48-";
	// 	nv-=48;
	// }//endwhile
	// if(nv%12==0){
	// 	ss<<abcPitch<<nv;
	// 	return ss.str();
	// }//endif
	// while(nv>24){
	// 	ss<<abcPitch<<"24-";
	// 	nv-=24;
	// }//endwhile
	// if(nv==18){
	// 	ss<<abcPitch<<18;
	// 	return ss.str();
	// }else if(nv==16){
	// 	ss<<"(3:2:1"<<abcPitch<<16;
	// 	return ss.str();
	// }else if(nv>12){
	// 	ss<<abcPitch<<"12-";
	// 	nv-=12;
	// }//endif
	// if(nv%3==0){
	// 	ss<<abcPitch<<nv;
	// 	return ss.str();
	// }else{//nv=2 or 4 or 8
	// 	ss<<"(3:2:1"<<abcPitch<<(3*nv)/2;
	// 	return ss.str();
	// }//endif
}//end GetAbcNote



#endif // BASICPITCHCALCULATION_HPP
