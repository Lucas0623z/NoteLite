/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#ifndef RealignmentMOHMM_HPP
#define RealignmentMOHMM_HPP

#define printOn false

#include<fstream>
#include<iostream>
#include<cmath>
#include<string>
#include<sstream>
#include<vector>
#include<algorithm>
#include<cfloat>
#include"stdio.h"
#include"stdlib.h"
#include"ScorePerfmMatch_v170503.hpp"
#include"Hmm_v170225.hpp"
#include"PianoRoll_v170503.hpp"
#include"HandSeparationForPR_v170304.hpp"

using namespace std;

class ScoreNote{
public:
	int pitch;
	string sitch;
	string fmt1ID;
	int noteStatus;//0(not yet found)/1(found)
	int hmmID1;//hmm.evts[hmmID1].sitchesPerCluster[hmmID2][hmmID3]
	int hmmID2;
	int hmmID3;

	void Print(){
cout<<"pitch,sitch,fmt1ID,noteStatus,hmmID1,2,3 : "<<pitch<<"\t"<<sitch<<"\t"<<fmt1ID<<"\t"<<noteStatus<<"\t"<<hmmID1<<","<<hmmID2<<","<<hmmID3<<endl;
	}//end Print

};//endclass ScoreNote

class LessScoreNote{
public:
	bool operator()(const ScoreNote& a, const ScoreNote& b){
		return a.pitch < b.pitch;
	}//end operator()
};//endclass LessScoreNote
//stable_sort(scoreNotes.begin(), scoreNotes.end(), LessScoreNote());

class PerfmNote{
public:
	int pitch;
	int noteID;
	int noteStatus;//0(correct)/1(extra)/2(substitution)/-1(unknown)
	int scoreNoteRef;

	void Print(){
cout<<"pitch,noteID,noteStatus,scoreNoteRef : "<<pitch<<"\t"<<noteID<<"\t"<<noteStatus<<"\t"<<scoreNoteRef<<endl;
	}//end Print

};//endclass PerfmNote

class LessPerfmNote{
public:
	bool operator()(const PerfmNote& a, const PerfmNote& b){
		return a.pitch < b.pitch;
	}//end operator()
};//endclass LessPerfmNote
//stable_sort(perfmNotes.begin(), perfmNotes.end(), LessPerfmNote());



class HMMState{
public:
	double reftime;
	vector<int> pitches;
	vector<string> sitches;
	vector<string> fmt1IDs;
	vector<int> stimes;
	Prob<int> outProb;
	vector<vector<int> > matchedNotes;

	HMMState(){
		outProb.Resize(128);
	}//end HMMState
	~HMMState(){
	}//end ~HMMState
	void Clear(){
		pitches.clear();
		sitches.clear();
		fmt1IDs.clear();
		stimes.clear();
	}//end Clear
	void SetOutProb(){
		outProb.P.assign(128,0.000001);
		for(int i=0;i<pitches.size();i+=1){
			outProb.P[pitches[i]]+=0.95;
			outProb.P[pitches[i]+1]+=0.0075;//0.015/2.
			outProb.P[pitches[i]-1]+=0.0075;
			outProb.P[pitches[i]+2]+=0.011;//0.022/2.
			outProb.P[pitches[i]-2]+=0.011;
			outProb.P[pitches[i]+12]+=0.00235;//0.0047/2.
			outProb.P[pitches[i]-12]+=0.00235;
			for(int dp=3;dp<12;dp+=1){
				outProb.P[pitches[i]-dp]+=0.00046111111;//0.0083/9./2.
				outProb.P[pitches[i]+dp]+=0.00046111111;
			}//endfor dp
		}//endfor i
		outProb.Normalize();
	}//end SetOutProb

};//endclass HMMState

class PartHMM{
public:
	vector<HMMState> states;
	Prob<int> iniProb;
//	vector<Prob<int> > trProb;//0:(i->i), 1:(i->i+1), 2:(i->i+2)
	void Clear(){
		states.clear();
	}//end Clear
};//endclass PartHMM

class MOHMM{
public:
	ScorePerfmMatch match;
	Hmm hmm;
	double secPerTick;
	PianoRoll pr,prL,prR;
	HandSeparationEngine handSepEng;
	vector<PartHMM> partHMMs;
	vector<double> trLP;
	Prob<int> pitchProb;
	vector<int> perfmIDs;
	vector<vector<int> > partAlignment;//Corresponds to perfmIDs. partAlignment[n][0,1,2]=part,stateID,noteID (partHMMs[i].states[j].fmt1IDs[k])
	int Nh;
	double facGauss;
	double facGauss2;
	double sig_t;
	double sig_t2;
	double facExp;
	double lambda;
	int minStime,maxStime;
	double minTime,maxTime;

	MOHMM(){
		Init();
	}//end MOHMM
	~MOHMM(){
	}//end ~MOHMM

	void Init(){
		Nh=50;
		partHMMs.resize(2);
		pitchProb.P.assign(256,0.0000001);//delta pitch dp P[dp+128]
		pitchProb.P[128]+=0.95;
		pitchProb.P[128+1]+=0.0075;//0.015/2.
		pitchProb.P[128-1]+=0.0075;
		pitchProb.P[128+2]+=0.011;//0.022/2.
		pitchProb.P[128-2]+=0.011;
		pitchProb.P[128+12]+=0.00235;//0.0047/2.
		pitchProb.P[128-12]+=0.00235;
		for(int dp=3;dp<12;dp+=1){
			pitchProb.P[128-dp]+=0.00046111111;//0.0083/9./2.
			pitchProb.P[128+dp]+=0.00046111111;
		}//endfor dp
		pitchProb.Normalize();

// i-3 -> i skip two clusters ln(0.001) = -6.907755
// i-2 -> i skip one cluster ln(0.049) = -3.015935
// i-1 -> i next cluster ln(0.75) = -0.287682
// i -> i self transition ln(0.2) = -1.6094379
		trLP.resize(4);
		trLP[0]=-1.6094379;
		trLP[1]=-0.287682;
		trLP[2]=-3.015935;
		trLP[3]=-6.907755;

//		sig_t=0.1;
		sig_t=0.05;
		facGauss=-0.5*log(2*M_PI)-log(sig_t);
		sig_t2=0.4;
		facGauss2=-0.5*log(2*M_PI)-log(sig_t2);
		lambda=0.0101;
		facExp=-log(lambda);

	}//end Init

	void SetScorePerfmMatch(ScorePerfmMatch match_){
		match=match_;
	}//end SetScorePerfmMatch

	void SetHmm(Hmm hmm_){
		hmm=hmm_;
	}//end SetHmm

	void SetSecPerTick(double secPerTick_){
		secPerTick=secPerTick_;
	}//end SetHmm

	void GetPianoRollFromHMM(int minStime_,int maxStime_,double minTime_,double maxTime_){
		assert(minStime_<maxStime_);
		assert(minTime_<maxTime_);
		minStime=minStime_;
		maxStime=maxStime_;
		minTime=minTime_;
		maxTime=maxTime_;
		SetSecPerTick( (maxTime-minTime)/double(maxStime-minStime) );
		pr.Clear();
		PianoRollEvt evt;
		for(int i=0;i<hmm.evts.size();i+=1){
			if(hmm.evts[i].stime<minStime || hmm.evts[i].stime>maxStime){continue;}
			evt.ontime=secPerTick*(hmm.evts[i].stime-minStime)+0.05*hmm.evts[i].internalPosition+minTime;
			evt.onvel=80;
			evt.offvel=80;
			evt.channel=0;
			if(hmm.evts[i].stateType!="TR"){
				evt.ID="X";
				for(int j=0;j<hmm.evts[i].sitchesPerCluster.size();j+=1){
					for(int k=0;k<hmm.evts[i].sitchesPerCluster[j].size();k+=1){
						if(hmm.IsDuplicate(hmm.evts[i].fmt1IDsPerCluster[j][k])){continue;}
						evt.ontime+=0.02*j;
						evt.offtime=evt.ontime+0.1;
						evt.sitch=hmm.evts[i].sitchesPerCluster[j][k];
						evt.pitch=SitchToPitch(evt.sitch);
						evt.label=hmm.evts[i].fmt1IDsPerCluster[j][k];
						evt.ext1=hmm.evts[i].stime;
						pr.evts.push_back(evt);
					}//endfor k
				}//endfor j
			}else{//hmm.evts[i].stateType=="TR"
				double startTime=evt.ontime;
				int numAlter=int((secPerTick*(hmm.evts[i].endstime-minStime)+minTime-startTime)/0.07);
				for(int alter=0;alter<numAlter;alter+=1){
					int j=alter%(hmm.evts[i].numClusters-1);
					for(int k=0;k<hmm.evts[i].sitchesPerCluster[j].size();k+=1){
						if(hmm.IsDuplicate(hmm.evts[i].fmt1IDsPerCluster[j][k])){continue;}
						evt.ontime=startTime+0.07*alter;
						evt.offtime=evt.ontime+0.1;
						evt.sitch=hmm.evts[i].sitchesPerCluster[j][k];
						evt.pitch=SitchToPitch(evt.sitch);
						evt.label=hmm.evts[i].fmt1IDsPerCluster[j][k];
						evt.ext1=hmm.evts[i].stime;
						pr.evts.push_back(evt);
					}//endfor k
				}//endfor alter
			}//endif
		}//endfor i
		pr.Sort();
		assert(pr.evts.size()>1);
	}//end GetPianoRollFromHMM

	void HandSep(){
		int maxPitch=pr.evts[0].pitch;
		int minPitch=pr.evts[0].pitch;
		for(int n=0;n<pr.evts.size();n+=1){
			if(pr.evts[n].pitch>maxPitch){maxPitch=pr.evts[n].pitch;}
			if(pr.evts[n].pitch<minPitch){minPitch=pr.evts[n].pitch;}
		}//endfor n
		handSepEng.SetPR(pr);
		handSepEng.SetInitialPitches(minPitch,maxPitch);
		handSepEng.SeparateHands();
		prL.Clear();
		prR.Clear();
		for(int n=0;n<pr.evts.size();n+=1){
			if(handSepEng.pr.evts[n].channel==0){
				prR.evts.push_back(handSepEng.pr.evts[n]);
			}else{
				prL.evts.push_back(handSepEng.pr.evts[n]);
				pr.evts[n].channel=1;
			}//endif
		}//endfor n

		if(prR.evts.size()==0){
			prR.evts.push_back(prL.evts[0]);
			prL.evts.erase(prL.evts.begin());
		}//endif
		if(prL.evts.size()==0){
			prL.evts.push_back(prR.evts[0]);
			prR.evts.erase(prR.evts.begin());
		}//endif
	}//end HandSep

	void ConstructPartHMMs(){
		vector<vector<int> > clusters;
		double thres=0.035;//35 ms for chord clustering
		vector<int> vi;
		HMMState state;

		/// Right-hand part HMM
		clusters.clear(); vi.clear();
		vi.push_back(0);
		for(int n=1;n<prR.evts.size();n+=1){
			if(prR.evts[n].ontime-prR.evts[n-1].ontime>thres){
				clusters.push_back(vi);
				vi.clear();
			}//endif
			vi.push_back(n);
		}//endfor n
		clusters.push_back(vi);

		partHMMs[0].Clear();
		for(int i=0;i<clusters.size();i+=1){
			double sum=0;
			state.Clear();
			for(int j=0;j<clusters[i].size();j+=1){
				sum+=prR.evts[clusters[i][j]].ontime;
				state.pitches.push_back(prR.evts[clusters[i][j]].pitch);
				state.sitches.push_back(prR.evts[clusters[i][j]].sitch);
				state.fmt1IDs.push_back(prR.evts[clusters[i][j]].label);
				state.stimes.push_back(prR.evts[clusters[i][j]].ext1);
			}//endfor j
			state.reftime=sum/clusters[i].size();
			state.SetOutProb();
			partHMMs[0].states.push_back(state);
		}//endfor i
		partHMMs[0].iniProb.P.assign(partHMMs[0].states.size(),0.1);
		partHMMs[0].iniProb.P[0]=0.9;
		partHMMs[0].iniProb.Normalize();

		/// Left-hand part HMM
		clusters.clear(); vi.clear();
		vi.push_back(0);
		for(int n=1;n<prL.evts.size();n+=1){
			if(prL.evts[n].ontime-prL.evts[n-1].ontime>thres){
				clusters.push_back(vi);
				vi.clear();
			}//endif
			vi.push_back(n);
		}//endfor n
		clusters.push_back(vi);

		partHMMs[1].Clear();
		for(int i=0;i<clusters.size();i+=1){
			double sum=0;
			state.Clear();
			for(int j=0;j<clusters[i].size();j+=1){
				sum+=prL.evts[clusters[i][j]].ontime;
				state.pitches.push_back(prL.evts[clusters[i][j]].pitch);
				state.sitches.push_back(prL.evts[clusters[i][j]].sitch);
				state.fmt1IDs.push_back(prL.evts[clusters[i][j]].label);
				state.stimes.push_back(prL.evts[clusters[i][j]].ext1);
			}//endfor j
			state.reftime=sum/clusters[i].size();
			state.SetOutProb();
			partHMMs[1].states.push_back(state);
		}//endfor i
		partHMMs[1].iniProb.P.assign(partHMMs[1].states.size(),0.1);
		partHMMs[1].iniProb.P[0]=0.9;
		partHMMs[1].iniProb.Normalize();

	}//end ConstructPartHMMs

	void GetPerformedNotes(){
ScorePerfmMatch subPerfm;
		perfmIDs.clear();
		for(int n=0;n<match.evts.size();n+=1){
			if(match.evts[n].ontime<minTime){continue;}
			if(match.evts[n].ontime>maxTime){break;}
subPerfm.evts.push_back(match.evts[n]);
			perfmIDs.push_back(n);
		}//endfor n
//subPerfm.WriteFile("subPerfm_match.txt");
	}//end GetPerformedNotes

	void Viterbi(){
if(printOn){cout<<"###Viterbi###"<<endl;}
/*
	i_s=0,1
	i_h=0,...,Nh-1
	iR=0,...,partHMMs[0].states.size()-1		,INI
	iL=0,...,partHMMs[1].states.size()-1		,INI
*/
		Nh=50;
		int length=perfmIDs.size();
		if(length<Nh){Nh=length;}

		vector<int> NStates(2);
		NStates[0]=partHMMs[0].states.size();
		NStates[1]=partHMMs[1].states.size();
		int NAll=2*Nh*NStates[0]*NStates[1];
/*
i=i_s+2*(i_h+Nh*(iR+NStates[0]*iL));
j=j_s+2*(j_h+Nh*(jR+NStates[0]*jL));
<->
i_s=i%2
i_h=(i/2)%Nh
iR=((i/2)/Nh)%NStates[0]
iL=(((i/2)/Nh)/NStates[0])%NStates[1]
*/

		vector<int> pitches;
		vector<double> ontimes;
		for(int i=0;i<length;i+=1){
			pitches.push_back(SitchToPitch(match.evts[perfmIDs[i]].sitch));
			ontimes.push_back(match.evts[perfmIDs[i]].ontime);
		}//endfor i

		vector<double> LP;
		vector<vector<int> > amax;
		amax.resize(length);
		for(int i=0;i<length;i+=1){amax[i].resize(NAll);}
		double logP;

		///Initial probability
		LP.assign(NAll,-DBL_MAX);
		for(int iR=0;iR<NStates[0];iR+=1){
			LP[2*Nh*iR]=partHMMs[0].iniProb.LP[iR]+partHMMs[0].states[iR].outProb.LP[pitches[0]];
		}//endfor iR
		for(int iL=0;iL<NStates[1];iL+=1){
			LP[1+2*Nh*NStates[0]*iL]=partHMMs[1].iniProb.LP[iL]+partHMMs[1].states[iL].outProb.LP[pitches[0]];
		}//endfor iL

		/// Viterbi update
		for(int n=1;n<length;n+=1){
//cout<<"Now Viterbi "<<(n+1)<<"/"<<length<<endl;

			vector<double> preLP(LP);
			LP.assign(NAll,-DBL_MAX);

			int i_s,i_h,iR,iL;
			/// L-to-R Constraint: jR=iR,iR-1,iR-2,iR-3
			/// L-to-R Constraint: jL=iL,iL-1,iL-2,iL-3

			for(int i=0;i<NAll;i+=1){//j->i
				int j;

				i_s=i%2;
				i_h=(i/2)%Nh;
				iR=((i/2)/Nh)%NStates[0];
				iL=(((i/2)/Nh)/NStates[0])%NStates[1];

				if(i_s==0){//right-hand (jL=iL)

					if(i_h==0){
//						j_s=1;
						for(int j_h=0;j_h<Nh;j_h+=1){
							if(n-j_h-2<-1){continue;}

							if(n-j_h-2==-1){//Initial condition -> jR = 0

								j=1+2*(j_h+Nh*(0+NStates[0]*iL));
//								logP=preLP[j]+partHMMs[0].iniProb.LP[iR]+facGauss-0.5*pow((ontimes[n]-ontimes[0]-(partHMMs[0].states[iR].reftime-partHMMs[1].states[iL].reftime))/sig_t,2.);//tau(iL)->tau(iR)
								logP=preLP[j]+partHMMs[0].iniProb.LP[iR]+facGauss2-0.5*pow((ontimes[n]-ontimes[0]-(partHMMs[0].states[iR].reftime-partHMMs[1].states[iL].reftime))/sig_t2,2.);//tau(iL)->tau(iR)

								if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

							}else{//n-j_h-2>=0

								//Self-transition jR=iR
								j=1+2*(j_h+Nh*(iR+NStates[0]*iL));
//								logP=preLP[j]+trLP[0]+facExp-(ontimes[n]-ontimes[n-j_h-2])/lambda;
								logP=preLP[j]+trLP[0]+0.9*(facExp-(ontimes[n]-ontimes[n-j_h-2])/lambda)+0.1*(facGauss2-0.5*pow((ontimes[n]-ontimes[n-j_h-2])/sig_t2,2.));
								if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

								for(int jR=iR-3;jR<iR;jR+=1){
									if(jR<0 || jR>=NStates[0]){continue;}
									j=1+2*(j_h+Nh*(jR+NStates[0]*iL));
									logP=preLP[j]+trLP[iR-jR]+facGauss-0.5*pow((ontimes[n]-ontimes[n-j_h-2]-(partHMMs[0].states[iR].reftime-partHMMs[0].states[jR].reftime))/sig_t,2.);
									if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}
								}//endfor jR

							}//endif

						}//endfor j_h

					}else{//i_h>0

						// j_h=i_h-1
						// j_s=0

						//Self-transition jR=iR
						j=2*(i_h-1+Nh*(iR+NStates[0]*iL));
//						logP=preLP[j]+trLP[0]+facExp-(ontimes[n]-ontimes[n-1])/lambda;
						logP=preLP[j]+trLP[0]+0.9*(facExp-(ontimes[n]-ontimes[n-1])/lambda)+0.1*(facGauss2-0.5*pow((ontimes[n]-ontimes[n-1])/sig_t2,2.));
						if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

						for(int jR=iR-3;jR<iR;jR+=1){
							if(jR<0 || jR>=NStates[0]){continue;}
							j=2*(i_h-1+Nh*(jR+NStates[0]*iL));
							logP=preLP[j]+trLP[iR-jR]+facGauss-0.5*pow((ontimes[n]-ontimes[n-1]-(partHMMs[0].states[iR].reftime-partHMMs[0].states[jR].reftime))/sig_t,2.);
							if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}
						}//endfor jR

					}//endif i_h

					LP[i]+=partHMMs[0].states[iR].outProb.LP[pitches[n]];

				}else if(i_s==1){//left-hand (jR=iR)

					if(i_h==0){
//						j_s=0;
						for(int j_h=0;j_h<Nh;j_h+=1){
							if(n-j_h-2<-1){continue;}

							if(n-j_h-2==-1){//Initial condition -> jL = 0

								j=2*(j_h+Nh*(iR));
//								logP=preLP[j]+partHMMs[1].iniProb.LP[iL]+facGauss-0.5*pow((ontimes[n]-ontimes[0]-(partHMMs[0].states[iL].reftime-partHMMs[0].states[iR].reftime))/sig_t,2.);//tau(iL)->tau(iR)
								logP=preLP[j]+partHMMs[1].iniProb.LP[iL]+facGauss2-0.5*pow((ontimes[n]-ontimes[0]-(partHMMs[0].states[iL].reftime-partHMMs[0].states[iR].reftime))/sig_t2,2.);//tau(iL)->tau(iR)

								if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

							}else{//n-j_h-2>=0

								//Self-transition jL=iL
								j=2*(j_h+Nh*(iR+NStates[0]*iL));
//								logP=preLP[j]+trLP[0]+facExp-(ontimes[n]-ontimes[n-j_h-2])/lambda;
								logP=preLP[j]+trLP[0]+0.9*(facExp-(ontimes[n]-ontimes[n-j_h-2])/lambda)+0.1*(facGauss2-0.5*pow((ontimes[n]-ontimes[n-j_h-2])/sig_t2,2.));
								if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

								for(int jL=iL-3;jL<iL;jL+=1){
									if(jL<0 || jL>=NStates[1]){continue;}
									j=2*(j_h+Nh*(iR+NStates[0]*jL));
									logP=preLP[j]+trLP[iL-jL]+facGauss-0.5*pow((ontimes[n]-ontimes[n-j_h-2]-(partHMMs[1].states[iL].reftime-partHMMs[1].states[jL].reftime))/sig_t,2.);
									if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}
								}//endfor jL

							}//endif

						}//endfor j_h

					}else{//i_h>0

						// j_h=i_h-1
						// j_s=1

						//Self-transition jL=iL
						j=1+2*(i_h-1+Nh*(iR+NStates[0]*iL));
//						logP=preLP[j]+trLP[0]+facExp-(ontimes[n]-ontimes[n-1])/lambda;
						logP=preLP[j]+trLP[0]+0.9*(facExp-(ontimes[n]-ontimes[n-1])/lambda)+0.1*(facGauss2-0.5*pow((ontimes[n]-ontimes[n-1])/sig_t2,2.));
						if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}

						for(int jL=iL-3;jL<iL;jL+=1){
							if(jL<0 || jL>=NStates[1]){continue;}
							j=1+2*(i_h-1+Nh*(iR+NStates[0]*jL));
							logP=preLP[j]+trLP[iL-jL]+facGauss-0.5*pow((ontimes[n]-ontimes[n-1]-(partHMMs[1].states[iL].reftime-partHMMs[1].states[jL].reftime))/sig_t,2.);
							if(logP>LP[i]){LP[i]=logP; amax[n][i]=j;}
						}//endfor jR

					}//endif i_h

					LP[i]+=partHMMs[1].states[iL].outProb.LP[pitches[n]];

				}//endif i_s

			}//endfor i

		}//endfor n

		/// Backtracking
		vector<int> optimalPath(length);
		double max=LP[0];
		optimalPath[length-1]=0;
		for(int i=0;i<NAll;i+=1){
			if(LP[i]>max){
				max=LP[i];
				optimalPath[length-1]=i;
			}//endif
		}//endfor i
		for(int n=length-2;n>=0;n-=1){
			optimalPath[n]=amax[n+1][optimalPath[n+1]];
		}//endfor n

		partAlignment.resize(length);
		for(int n=0;n<length;n+=1){
			partAlignment[n].resize(3);
			partAlignment[n][0]=optimalPath[n]%2;
			if(partAlignment[n][0]==0){//RH
				partAlignment[n][1]=((optimalPath[n]/2)/Nh)%NStates[0];
			}else{//LH
				partAlignment[n][1]=(((optimalPath[n]/2)/Nh)/NStates[0])%NStates[1];
			}//endif

			max=pitchProb.P[pitches[n]-partHMMs[partAlignment[n][0]].states[partAlignment[n][1]].pitches[0]+128];
			partAlignment[n][2]=0;//note ID in the state
			for(int k=0;k<partHMMs[partAlignment[n][0]].states[partAlignment[n][1]].pitches.size();k+=1){
				if(pitchProb.P[pitches[n]-partHMMs[partAlignment[n][0]].states[partAlignment[n][1]].pitches[k]+128]>max){
					max=pitchProb.P[pitches[n]-partHMMs[partAlignment[n][0]].states[partAlignment[n][1]].pitches[k]+128];
					partAlignment[n][2]=k;
				}//endif
			}//endfor k

//cout<<n<<"\t"<<PitchToSitch(pitches[n])<<"\t"<<ontimes[n]<<"\t"<<partAlignment[n][0]<<"\t"<<partAlignment[n][1]<<"\t"<<partAlignment[n][2]<<"\t"<<partHMMs[partAlignment[n][0]].states[partAlignment[n][1]].fmt1IDs[partAlignment[n][2]]<<endl;

		}//endfor n

	}//end Viterbi


	void DetectErrors(){//Should be improved

	/// Add previously matched reference notes to missing notes
{
		MissingNote missNote;
		for(int n=0;n<perfmIDs.size();n+=1){
			if(match.evts[perfmIDs[n]].errorInd>1){continue;}
			missNote.stime=match.evts[perfmIDs[n]].stime;
			missNote.fmt1ID=match.evts[perfmIDs[n]].fmt1ID;
			assert(missNote.stime>=minStime && missNote.stime<=maxStime);
			match.missingNotes.push_back(missNote);
		}//endfor n
}//

		for(int i_s=0;i_s<2;i_s+=1){//For each part HMM
			for(int i=0;i<partHMMs[i_s].states.size();i+=1){
				double refT=partHMMs[i_s].states[i].reftime;

				vector<PerfmNote> perfmClusterContent;
{
				PerfmNote perfmNote;
				for(int m=0;m<partAlignment.size();m+=1){
					if(partAlignment[m][0]!=i_s || partAlignment[m][1]!=i){continue;}
					perfmNote.pitch=SitchToPitch(match.evts[perfmIDs[m]].sitch);
					perfmNote.noteID=m;
					perfmNote.noteStatus=-1;
					perfmClusterContent.push_back(perfmNote);
					partAlignment[m][2]=-1;
				}//endfor m
}//
				if(perfmClusterContent.size()==0){continue;}
				stable_sort(perfmClusterContent.begin(), perfmClusterContent.end(), LessPerfmNote());

				vector<ScoreNote> scoreClusterContent;
{
				ScoreNote scoreNote;
				for(int j=0;j<partHMMs[i_s].states[i].fmt1IDs.size();j+=1){
					scoreNote.pitch=partHMMs[i_s].states[i].pitches[j];
					scoreNote.sitch=partHMMs[i_s].states[i].sitches[j];
					scoreNote.fmt1ID=partHMMs[i_s].states[i].fmt1IDs[j];
					scoreNote.noteStatus=0;
					scoreNote.hmmID1=i_s;
					scoreNote.hmmID2=i;
					scoreNote.hmmID3=j;
					scoreClusterContent.push_back(scoreNote);
				}//endfor j
}//
				stable_sort(scoreClusterContent.begin(), scoreClusterContent.end(), LessScoreNote());

if(printOn){
//####################################################################################
cout<<"-----------------------------------------------"<<endl;
cout<<"### scoreClusterContent ###"<<endl;
	for(int m=0;m<scoreClusterContent.size();m+=1){
		scoreClusterContent[m].Print();
	}//endfor m
cout<<"### perfmClusterContent ###"<<endl;
	for(int m=0;m<perfmClusterContent.size();m+=1){
		perfmClusterContent[m].Print();
	}//endfor m
//####################################################################################
}

				/// Select best synchronised performed note for each pitch -> others are extra notes
				/// Identify correct notes
{
				int count;
				int amin;
				double min;
				for(int m=0;m<perfmClusterContent.size();m+=1){
					count=1;
					amin=m;
					min=abs(match.evts[perfmIDs[perfmClusterContent[m].noteID]].ontime-refT);
					perfmClusterContent[m].noteStatus=1;
					for(int mp=m+1;mp<perfmClusterContent.size();mp+=1){
						if(perfmClusterContent[mp].pitch!=perfmClusterContent[m].pitch){break;}
						count+=1;
						perfmClusterContent[mp].noteStatus=1;
						if(abs(match.evts[perfmIDs[perfmClusterContent[mp].noteID]].ontime-refT)<min){
							amin=mp;
							min=abs(match.evts[perfmIDs[perfmClusterContent[mp].noteID]].ontime-refT);
						}//endif
					}//endfor mp
					perfmClusterContent[amin].noteStatus=-1;
					for(int l=0;l<scoreClusterContent.size();l+=1){
						if(perfmClusterContent[amin].pitch==scoreClusterContent[l].pitch){
							perfmClusterContent[amin].noteStatus=0;
							perfmClusterContent[amin].scoreNoteRef=l;
							scoreClusterContent[l].noteStatus=1;
							match.evts[perfmIDs[perfmClusterContent[amin].noteID]].fmt1ID=scoreClusterContent[l].fmt1ID;
							match.evts[perfmIDs[perfmClusterContent[amin].noteID]].stime=partHMMs[i_s].states[i].stimes[scoreClusterContent[l].hmmID3];
							match.evts[perfmIDs[perfmClusterContent[amin].noteID]].sitch=scoreClusterContent[l].sitch;
							match.evts[perfmIDs[perfmClusterContent[amin].noteID]].errorInd=0;
							break;
						}//endif
					}//endfor l
					m=m+count-1;
				}//endfor m
}//
				/// Retain only unidentified performed notes
				for(int m=perfmClusterContent.size()-1;m>=0;m-=1){
					if(perfmClusterContent[m].noteStatus==1){//extra note
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].fmt1ID="*";
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].stime=-1;
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].errorInd=3;
						perfmClusterContent.erase(perfmClusterContent.begin()+m);
					}else if(perfmClusterContent[m].noteStatus==0){
						perfmClusterContent.erase(perfmClusterContent.begin()+m);
					}//endif
				}//endfor m

if(printOn){
//####################################################################################
cout<<"### perfmClusterContent 2 ###"<<endl;
	for(int m=0;m<perfmClusterContent.size();m+=1){
		perfmClusterContent[m].Print();
	}//endfor m
//####################################################################################
}

				/// Identify pitch error or extra note
				int scoreClusterSize=scoreClusterContent.size();
				for(int l=-1;l<scoreClusterSize;l+=1){

					int minPitch=-1;
					int maxPitch=500;

					if(l>=0){
						minPitch=scoreClusterContent[l].pitch;
					}//endif
					vector<int> SCIDs;//ID for notes in score cluster content
					for(int lp=l+1;lp<scoreClusterContent.size();lp+=1){
						l=lp-1;
						if(scoreClusterContent[lp].noteStatus==1){
							maxPitch=scoreClusterContent[lp].pitch;
							break;
						}//endif
						SCIDs.push_back(lp);
						if(lp==scoreClusterContent.size()-1 && scoreClusterContent[lp].noteStatus==0){
							l=lp;
						}//endif
					}//endfor lp

					vector<int> PCIDs;//ID for notes in perform cluster content
					for(int m=0;m<perfmClusterContent.size();m+=1){
						if(perfmClusterContent[m].pitch>minPitch && perfmClusterContent[m].pitch<maxPitch){
							PCIDs.push_back(m);
							perfmClusterContent[m].noteStatus=1;//(temporary) extra note
						}//endif
					}//endfor m

if(printOn){
//####################################################################################
cout<<"l,minPitch,maxPitch : "<<l<<"\t"<<minPitch<<"\t"<<maxPitch<<endl;
cout<<"### SCIDs ###"<<endl;
	for(int m=0;m<SCIDs.size();m+=1){
cout<<SCIDs[m]<<"\t";
	}//endfor m
cout<<endl;
cout<<"### PCIDs ###"<<endl;
	for(int m=0;m<PCIDs.size();m+=1){
cout<<PCIDs[m]<<"\t";
	}//endfor m
cout<<endl;
//####################################################################################
}

					if(PCIDs.size()==0){continue;}
					if(SCIDs.size()==0){
						for(int mm=0;mm<PCIDs.size();mm+=1){
							perfmClusterContent[PCIDs[mm]].noteStatus=1;//extra note
						}//endfor mm
						continue;
					}//endif

					if(PCIDs.size()==SCIDs.size()){
						for(int mm=0;mm<PCIDs.size();mm+=1){
							perfmClusterContent[PCIDs[mm]].noteStatus=2;//pitch error
							perfmClusterContent[PCIDs[mm]].scoreNoteRef=SCIDs[mm];
						}//endfor mm
						continue;
					}//endif

					/// Reach here only if (PCIDs.size()>1 or SCIDs.size()>1)
					/// note-wise LR alignment for (minPitch,maxPitch)
					int stateSize=PCIDs.size()+2;//state = 0(N/A) / PCID+1 / 9999(N/A)
					vector<double> LP(stateSize);
					vector<vector<int> > amax(SCIDs.size());
					for(int i=0;i<SCIDs.size();i+=1){amax[i].resize(stateSize);}

					//Initial probability (uniform);
					LP[0]=-100;
					for(int i=1;i<stateSize-1;i+=1){
						LP[i]=pitchProb.P[perfmClusterContent[PCIDs[i-1]].pitch-scoreClusterContent[SCIDs[0]].pitch+128];
					}//endfor i
					LP[stateSize-1]=-100;

					double logP;
					for(int t=1;t<SCIDs.size();t+=1){
						vector<double> preLP(LP);

						LP[0]=preLP[0]-100;
						amax[t][0]=0;

						for(int i=1;i<stateSize-1;i+=1){
							amax[t][i]=0;
							LP[i]=preLP[0];
							for(int j=1;j<i;j+=1){
								logP=preLP[j];
								if(logP>LP[i]){LP[i]=logP;amax[t][i]=j;}//endif
							}//endfor j					
							LP[i]+=pitchProb.P[perfmClusterContent[PCIDs[i-1]].pitch-scoreClusterContent[SCIDs[t]].pitch+128];
						}//endfor i

							amax[t][stateSize-1]=stateSize-1;
							LP[stateSize-1]=preLP[stateSize-1];
							for(int j=1;j<stateSize-1;j+=1){
								logP=preLP[j];
								if(logP>LP[stateSize-1]){LP[stateSize-1]=logP;amax[t][stateSize-1]=j;}//endif
							}//endfor j
							LP[stateSize-1]-=100;

					}//endfor t

					vector<int> optPath(SCIDs.size());
					optPath[SCIDs.size()-1]=0;
					double max=LP[0];
					for(int i=1;i<stateSize;i+=1){
						if(LP[i]>max){
							max=LP[i];
							optPath[SCIDs.size()-1]=i;
						}//endif
					}//endfor i
					for(int t=SCIDs.size()-2;t>=0;t-=1){
						optPath[t]=amax[t+1][optPath[t+1]];
					}//endfor t

					for(int i=0;i<SCIDs.size();i+=1){
						if(optPath[i]==0 || optPath[i]==PCIDs.size()+1){continue;}
						perfmClusterContent[PCIDs[optPath[i]-1]].noteStatus=2;//pitch error
						perfmClusterContent[PCIDs[optPath[i]-1]].scoreNoteRef=SCIDs[i];
					}//endfor i

				}//endfor l

				for(int m=0;m<perfmClusterContent.size();m+=1){
					if(perfmClusterContent[m].noteStatus==1){//extra note
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].fmt1ID="*";
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].stime=-1;
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].errorInd=3;
					}else if(perfmClusterContent[m].noteStatus==2){//pitch error
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].fmt1ID=scoreClusterContent[perfmClusterContent[m].scoreNoteRef].fmt1ID;
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].stime=partHMMs[i_s].states[i].stimes[scoreClusterContent[perfmClusterContent[m].scoreNoteRef].hmmID3];
						match.evts[perfmIDs[perfmClusterContent[m].noteID]].errorInd=1;
					}else{//never reach here
if(printOn){cout<<"part,stateID : "<<i_s<<"\t"<<i<<"\t"<<"!!!!!"<<endl;}
						assert(false);
					}//endif
				}//endfor m

			}//endfor i
		}//endfor i_s

		/// Delete newly-matched old missing notes
		for(int i=match.missingNotes.size()-1;i>=0;i-=1){
			if(match.missingNotes[i].stime<minStime || match.missingNotes[i].stime>maxStime){continue;}
			for(int n=0;n<perfmIDs.size();n+=1){
				if(match.evts[perfmIDs[n]].fmt1ID==match.missingNotes[i].fmt1ID){
					match.missingNotes.erase(match.missingNotes.begin()+i);
					break;
				}//endif
			}//endfor n
		}//endfor i

	}//endfor DetectErrors

	void Realign(int minStime_,int maxStime_,double minTime_,double maxTime_){
		GetPianoRollFromHMM(minStime_,maxStime_,minTime_,maxTime_);
		HandSep();
		ConstructPartHMMs();
		GetPerformedNotes();
//		pr.WriteFileSpr("subPR.txt");
//		prL.WriteFileSpr("subPRL.txt");
//		prR.WriteFileSpr("subPRR.txt");
		Viterbi();
		DetectErrors();
	}//end Realign


};//endclass MOHMM

#endif // RealignmentMOHMM_HPP
