/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#ifndef HandSeparationForPR_HPP
#define HandSeparationForPR_HPP

#define printOn false

#include<fstream>
#include<iostream>
#include<cmath>
#include<string>
#include<sstream>
#include<vector>
#include<algorithm>
#include"stdio.h"
#include"stdlib.h"
#include"PianoRoll_v170503.hpp"
#include"HandSeparationData_MergedOututHMM_v161230.hpp"

using namespace std;

class HandSeparationEngine{
public:
	PianoRoll pr;

	vector<vector<double> > Lprob;
	vector<vector<double> > uniLprob;
	vector<double> LRLprob;
	int iniPitchLH,iniPitchRH;

	HandSeparationEngine(){
		Init();
	}//end HandSeparationEngine
	~HandSeparationEngine(){
	}//end ~HandSeparationEngine

	void Init(){
		HandSeparationData_MergedOutputHMM data;
		Lprob=data.Lprob;
		uniLprob=data.uniLprob;
		LRLprob=data.LRLprob;
		iniPitchLH=53;
		iniPitchRH=71;
	}//end Init

	void SetInitialPitches(int pitchLH,int pitchRH){
		iniPitchLH=pitchLH;
		iniPitchRH=pitchRH;
	}//end SetInitialPitches

	void SetPR(PianoRoll pr_){
		pr=pr_;
	}//end SetPR

	void SeparateHands(){//chan= 0:Right Hand, 1:Left Hand

		vector<int> v(10);

		int length=pr.evts.size();
		int dp_c=15;
		int handPartPreference[length][2];//HandPartPreference[m][0]=1 if m-th note is likely to be in the right-hand-part
		vector<int> pitch;
		for(int n=0;n<length;n+=1){
			PianoRollEvt evt=pr.evts[n];
			handPartPreference[n][0]=0;
			handPartPreference[n][1]=0;
			int p_cur=evt.pitch;
			int p_max=p_cur;
			int p_min=p_cur;
			pitch.push_back(p_cur);
			for(int m=0;m<length;m+=1){
				if(pr.evts[m].offtime < evt.ontime){continue;}
				if(pr.evts[m].ontime  > evt.offtime){break;}
				int p=SitchToPitch(pr.evts[m].sitch);
				if(p>p_max){p_max=p;}
				if(p<p_min){p_min=p;}
			}//endfor m
			if(p_cur>p_min+dp_c){handPartPreference[n][0]=1;}//likely to be in the right-hand-part
			if(p_cur<p_max-dp_c){handPartPreference[n][1]=1;}//likely to be in the left-hand-part
		}//endfor n

		int Nh=50;
		vector<double> LP;//k=2*h+sig
		LP.assign(2*Nh,-1000);
		vector<vector<int> > argmaxHist;
		LP[0]=Lprob[0][pitch[0]-iniPitchRH+128];
		LP[1]=Lprob[1][pitch[0]-iniPitchLH+128];
		for(int n=1;n<length;n+=1){
			double max,logP;
			vector<double> preLP(LP);
			vector<int> argmax(2*Nh);
			for(int i=0;i<2*Nh;i+=1){//j -> i
				max=preLP[i]-10000;
				argmax[i]=i;
				for(int j=0;j<2*Nh;j+=1){
					if(j%2==i%2 && j/2==i/2-1){
						logP=preLP[j]+LRLprob[i%2]+Lprob[i%2][pitch[n]-pitch[n-1]+128];
						if(logP>max){max=logP; argmax[i]=j;}
					}//endif
					if(j%2!=i%2 && i/2==0){
						if(n-2-j/2>=0){
							logP=preLP[j]+LRLprob[i%2]+Lprob[i%2][pitch[n]-pitch[n-2-j/2]+128];
						}else{
							logP=preLP[j]+LRLprob[i%2]+Lprob[i%2][pitch[n]-((i%2==0)? iniPitchRH:iniPitchLH)+128];
						}//endif
						if(logP>max){max=logP; argmax[i]=j;}
					}//endif
				}//endfor j
				if(i%2==0){
					v[1]=53;
					if(n-1-i/2>=0){v[1]=pitch[n-1-i/2];}
					LP[i]=max+((v[1]<pitch[n])? 0:-4.605)+((handPartPreference[n][0]>0)? -0.0202027:-0.693147)+((handPartPreference[n][1]>0)? -3.912023:-0.693147);
				}else{
					v[0]=71;
					if(n-1-i/2>=0){v[0]=pitch[n-1-i/2];}
					LP[i]=max+((v[0]>pitch[n])? 0:-4.605)+((handPartPreference[n][0]>0)? -3.912023:-0.693147)+((handPartPreference[n][1]>0)? -0.0202027:-0.693147);
				}//endif
			}//endfor i
			argmaxHist.push_back(argmax);
		}//endfor n

		vector<int> estStates(length);
		double max=LP[0];
		int amax=0;
		for(int i=0;i<LP.size();i+=1){if(LP[i]>max){max=LP[i]; amax=i;}}
		estStates[length-1]=amax;
		for(int n=0;n<length-1;n+=1){
			amax=argmaxHist[length-2-n][amax];
			estStates[length-2-n]=amax;
		}//endfor n

		for(int n=0;n<length;n+=1){
			pr.evts[n].channel=estStates[n]%2;
		}//endfor n

	}//end SeparateHands


};//endclass HandSeparationEngine

#endif // HandSeparationForPR_HPP
