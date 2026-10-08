/*
Copyright 2019 Eita Nakamura

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
*/
#include<fstream>
#include<iostream>
#include<cmath>
#include<string>
#include<sstream>
#include<vector>
#include<cassert>
#include"stdio.h"
#include"stdlib.h"
#include<algorithm>
#include"BasicCalculation_v170122.hpp"
#include"Hmm_v170225.hpp"
#include"ScorePerfmMatch_v170503.hpp"
#include"PianoRoll_v170503.hpp"
using namespace std;

struct Observation{
	double ioi;
	int pitch;
};

class ScoreFollower{
public:
	Hmm hmm;//score infomation
	int TPQN_;
	bool isFirst_;

	int nState_;
	int currentState_;
	int previousState_;
	double tickPerSec_;
	double initialTickPerSec_; // for reset score follower
	double lastTickPerSec_;
	double currentOnsetTime_;
	double previousOnsetTime_;
	double predictedNextTime_;

	vector<double> tempo_;
	vector<double> like_;
	vector<vector<int> > amaxHist_;
	vector<vector<int> > pitchList_;
	vector<vector<string> > scorePosList_;
	vector<int> inputPitch_;
	vector<double> timeHist;
	int D1_,D2_;

	vector<int> Stime,EndStime,TopId,BotId;
	vector<string> Type;
	vector<vector<vector<int> > > PitchClusters,VoiceClusters;
	vector<vector<vector<string> > > RefClusters;
	vector<vector<double> > IOIWeight;
	vector<double> stolenTime;

	vector<vector<double> > PitchLP;
	vector<vector<vector<double> > > InternalTrLP;
	vector<double> TopTrLP;
	double iniSecPerTick;
	double logTrSkipLP;

	double Sig_t,Sig_v,M_;
	double LPLambda_[2];
	vector<double> LPSwitch_;
	double SwSecPerTick_[2];
	double SwM_[2];
	double SwSig_t[2];

	vector<double> pitchDiffProb_;

	ScoreFollower(string hmmName,double secPerQN){
		vector<int> v(100);
		vector<double> d(100);
		vector<string> s(100);
		vector<int> vi;
		vector<vector<int> > vvi;
		vector<string> vs;
		vector<vector<string> > vvs;
		vector<int> vpitch;
		vector<string> vref;

		hmm.ReadFile(hmmName);
		TPQN_=hmm.TPQN;

		int curTopId=-1;
		for(int n=0;n<hmm.evts.size();n+=1){
			if(hmm.evts[n].internalPosition==1){curTopId+=1;}
			Stime.push_back(hmm.evts[n].stime);
			EndStime.push_back(hmm.evts[n].endstime);
			TopId.push_back(curTopId);
			BotId.push_back(hmm.evts[n].internalPosition);
			Type.push_back(hmm.evts[n].stateType);

			vvi.clear();
			for(int i=0;i<hmm.evts[n].numClusters;i+=1){
				vi.clear();
				for(int j=0;j<hmm.evts[n].numNotesPerCluster[i];j+=1){
					vi.push_back(SitchToPitch(hmm.evts[n].sitchesPerCluster[i][j]));
				}//endfor j
				vvi.push_back(vi);
			}//endfor i
			PitchClusters.push_back(vvi);
			VoiceClusters.push_back(hmm.evts[n].voicesPerCluster);
			RefClusters.push_back(hmm.evts[n].fmt1IDsPerCluster);

			vector<double> selfTransitionWeight;//0=chord, 1=arp, 2=sa, 3=trill
			selfTransitionWeight.assign(4,0.01);
			if(hmm.evts[n].stateType!="TR"){
				selfTransitionWeight[0]+=hmm.evts[n].numCh;
				selfTransitionWeight[1]+=hmm.evts[n].numArp;
				selfTransitionWeight[2]+=hmm.evts[n].numInterCluster;
				Norm(selfTransitionWeight);
				stolenTime.push_back((hmm.evts[n].numArp*0.13>hmm.evts[n].numInterCluster*0.13)? hmm.evts[n].numArp*0.13:hmm.evts[n].numInterCluster*0.13);
			}else{//if TR
				for(int j=0;j<hmm.evts[n].numClusters;j+=1){
					selfTransitionWeight[0]+=hmm.evts[n].numNotesPerCluster[j]-1;
					selfTransitionWeight[3]+=1;
				}//endfor j
				Norm(selfTransitionWeight);
				stolenTime.push_back(0);
			}//endif
			IOIWeight.push_back(selfTransitionWeight);
		}//endfor n

		nState_=Stime.size();
		assert(nState_>=1);
		like_.resize(nState_);
		assert((int)like_.size()==nState_);
		iniSecPerTick=secPerQN/double(TPQN_);
		initialTickPerSec_=1./iniSecPerTick;
		lastTickPerSec_=initialTickPerSec_;
//cout<<"nState_ nTopState: "<<nState_<<"\t"<<TopId[nState_-1]<<endl;

	/////////////// trill overlaps

		for(int i=1;i<nState_;i+=1){
			if(Type[i]=="TR"&&BotId[i]>1){
				vi.clear();
				for(int k=0;k<PitchClusters[i].size();k+=1){
					for(int l=0;l<PitchClusters[i][k].size();l+=1){
						vi.push_back(PitchClusters[i][k][l]);
					}//endfor l
				}//endfor k
				for(int j=i-1;j>=i-BotId[i]+1;j-=1){
					PitchClusters[j].push_back(vi);
				}//endfor j
				vi.clear();
				for(int k=0;k<PitchClusters[i].size();k+=1){
					for(int l=0;l<PitchClusters[i][k].size();l+=1){
						vi.push_back(-1);
					}//endfor l
				}//endfor k
				for(int j=i-1;j>=i-BotId[i]+1;j-=1){
					VoiceClusters[j].push_back(vi);
				}//endfor j
				vs.clear();
				for(int k=0;k<PitchClusters[i].size();k+=1){
					for(int l=0;l<PitchClusters[i][k].size();l+=1){
						vs.push_back(RefClusters[i][k][l]);
					}//endfor l
				}//endfor k
				for(int j=i-1;j>=i-BotId[i]+1;j-=1){
					RefClusters[j].push_back(vs);
				}//endfor j
			}//endif
		}//endfor i

	/////////////// pitch output probability

	{
		vector<double> vd;
		for(int i=0;i<nState_;i+=1){

			vpitch.clear();
			vref.clear();
			for(int j=0;j<PitchClusters[i].size();j+=1){
				for(int k=0;k<PitchClusters[i][j].size();k+=1){
					vpitch.push_back(PitchClusters[i][j][k]);
					vref.push_back(RefClusters[i][j][k]);
				}//endfor k
			}//endfor j
			pitchList_.push_back(vpitch);
			scorePosList_.push_back(vref);

			vd.assign(128,0.000001);//all pitches
			if(Type[i]!="TR"){
				for(int j=0;j<PitchClusters[i].size();j+=1){
					for(int k=0;k<PitchClusters[i][j].size();k+=1){
						d[0]=0.95;//chordal
						if(VoiceClusters[i][j][k]<0){d[0]/=2.;}//endif
						vd[PitchClusters[i][j][k]]+=d[0];
						d[0]=0.015/2.;//semi-tone
						if(VoiceClusters[i][j][k]<0){d[0]/=2.;}//endif
						vd[PitchClusters[i][j][k]+1]+=d[0];
						vd[PitchClusters[i][j][k]-1]+=d[0];
						d[0]=0.022/2.;//whole-tone
						if(VoiceClusters[i][j][k]<0){d[0]/=2.;}//endif
						vd[PitchClusters[i][j][k]+2]+=d[0];
						vd[PitchClusters[i][j][k]-2]+=d[0];
						d[0]=0.0047/2.;//octave
						if(VoiceClusters[i][j][k]<0){d[0]/=2.;}//endif
						vd[PitchClusters[i][j][k]+12]+=d[0];
						vd[PitchClusters[i][j][k]-12]+=d[0];
						d[0]=0.0083/9./2.;//within-one-octave
						if(VoiceClusters[i][j][k]<0){d[0]/=2.;}//endif
						for(int pp=1;pp<12;pp+=1){
							if(pp==1||pp==2){continue;}
							vd[PitchClusters[i][j][k]+pp]+=d[0];
							vd[PitchClusters[i][j][k]-pp]+=d[0];
						}//endfor pp
					}//endfor k
				}//endfor j
			}else{//if TR
				d[1]=0;
				for(int j=0;j<PitchClusters[i].size()-1;j+=1){
					for(int k=0;k<PitchClusters[i][j].size();k+=1){
						d[1]+=1;
						d[0]=0.95;//chordal
						vd[PitchClusters[i][j][k]]+=d[0];
						d[0]=0.015/2.;//semi-tone
						vd[PitchClusters[i][j][k]+1]+=d[0];
						vd[PitchClusters[i][j][k]-1]+=d[0];
						d[0]=0.022/2.;//whole-tone
						vd[PitchClusters[i][j][k]+2]+=d[0];
						vd[PitchClusters[i][j][k]-2]+=d[0];
						d[0]=0.0047/2.;//octave
						vd[PitchClusters[i][j][k]+12]+=d[0];
						vd[PitchClusters[i][j][k]-12]+=d[0];
						d[0]=0.0083/9./2.;//within-one-octave
						for(int pp=1;pp<12;pp+=1){
							if(pp==1||pp==2){continue;}
							vd[PitchClusters[i][j][k]+pp]+=d[0];
							vd[PitchClusters[i][j][k]-pp]+=d[0];
						}//endfor pp
					}//endfor k
				}//endfor j
				int jj=PitchClusters[i].size()-1;
				double factor=1./(d[1]*iniSecPerTick*(EndStime[i]-Stime[i])/0.15);
				for(int k=0;k<PitchClusters[i][jj].size();k+=1){
					d[0]=0.95;//chordal
					vd[PitchClusters[i][jj][k]]+=d[0]*factor;
					d[0]=0.015/2.;//semi-tone
					vd[PitchClusters[i][jj][k]+1]+=d[0]*factor;
					vd[PitchClusters[i][jj][k]-1]+=d[0]*factor;
					d[0]=0.022/2.;//whole-tone
					vd[PitchClusters[i][jj][k]+2]+=d[0]*factor;
					vd[PitchClusters[i][jj][k]-2]+=d[0]*factor;
					d[0]=0.0047/2.;//octave
					vd[PitchClusters[i][jj][k]+12]+=d[0]*factor;
					vd[PitchClusters[i][jj][k]-12]+=d[0]*factor;
					d[0]=0.0083/9./2.;//within-one-octave
					for(int pp=1;pp<12;pp+=1){
						if(pp==1||pp==2){continue;}
						vd[PitchClusters[i][jj][k]+pp]+=d[0]*factor;
						vd[PitchClusters[i][jj][k]-pp]+=d[0]*factor;
					}//endfor pp
				}//endfor k
			}//endif
			Norm(vd);
			for(int j=0;j<vd.size();j+=1){vd[j]=log(vd[j]);}
			PitchLP.push_back(vd);
		}//endfor i
	}//

	/////////////// internal transition probability
	{
		vector<vector<double> > LP(102);//0=in, 1--100=states, 101=out
		vector<double> selfTrProbability;
		int prevTopId=0;
		for(int i=0;i<nState_;i+=1){
			if(Type[i]!="TR"){
				d[0]=0;
				for(int j=0;j<PitchClusters[i].size();j+=1){
					if(PitchClusters[i][j].size()>0){
						d[0]+=PitchClusters[i][j].size()*((VoiceClusters[i][j][0]<0)? 0.5:1.);
					}//endif
				}//endfor j
				selfTrProbability.push_back((d[0]-1+0.1)/(d[0]+0.1));
			}else{//if TR
				d[1]=0;
				for(int j=0;j<PitchClusters[i].size()-1;j+=1){
					d[1]+=PitchClusters[i][j].size();
				}//endfor j
				d[1]/=(PitchClusters[i].size()-1);
				d[0]=d[1]*(iniSecPerTick*(EndStime[i]-Stime[i]))/0.15;
				if(d[0]<3){d[0]=3;}
				selfTrProbability.push_back((d[0]-1+0.1)/(d[0]+0.1));
			}//endif
			if(prevTopId!=TopId[i]){
				for(int j=0;j<102;j+=1){LP[j].assign(102,-1000);}
				LP[0][1]=log(1-0.1);
				for(int j=2;j<=BotId[i-1];j+=1){LP[0][j]=log(0.1/(BotId[i-1]-1));}//endfor j
				Lognorm(LP[0]);
				for(int j=1;j<=BotId[i-1];j+=1){
					if(j==BotId[i-1]){
						LP[j][j]=log(selfTrProbability[i-BotId[i-1]+j-1]);
						LP[j][101]=log(1-selfTrProbability[i-BotId[i-1]+j-1]);
					}else{
						LP[j][j]=log(selfTrProbability[i-BotId[i-1]+j-1]);
						LP[j][j+1]=log(0.9*(1-selfTrProbability[i-BotId[i-1]+j-1]));
						for(int k=j+2;k<=BotId[i-1];k+=1){
							LP[j][k]=log(0.1/(BotId[i-1]-j)*(1-selfTrProbability[i-BotId[i-1]+j-1]));
						}//endfor k
						LP[j][101]=log(0.1/(BotId[i-1]-j)*(1-selfTrProbability[i-BotId[i-1]+j-1]));
					}//endif
					Lognorm(LP[j]);
				}//endfor j
				InternalTrLP.push_back(LP);
			}//endif
			prevTopId=TopId[i];
		}//endfor i
		for(int j=0;j<102;j+=1){LP[j].assign(102,-1000);}
		LP[0][1]=log(1-0.1);
		for(int j=2;j<=BotId[nState_-1];j+=1){LP[0][j]=log(0.1/(BotId[nState_-1]-1));}//endfor j
		Lognorm(LP[0]);
		for(int j=1;j<=BotId[nState_-1];j+=1){
			if(j==BotId[nState_-1]){
				LP[j][j]=log(selfTrProbability[nState_-BotId[nState_-1]+j-1]);
				LP[j][101]=log(1-selfTrProbability[nState_-BotId[nState_-1]+j-1]);
			}else{
				LP[j][j]=log(selfTrProbability[nState_-BotId[nState_-1]+j-1]);
				LP[j][j+1]=log(0.9*(1-selfTrProbability[nState_-BotId[nState_-1]+j-1]));
				for(int k=j+2;k<=BotId[nState_-1];k+=1){
					LP[j][k]=log(0.1/(BotId[nState_-1]-j)*(1-selfTrProbability[nState_-BotId[nState_-1]+j-1]));
				}//endfor k
				LP[j][101]=log(0.1/(BotId[nState_-1]-j)*(1-selfTrProbability[nState_-BotId[nState_-1]+j-1]));
			}//endif
			Lognorm(LP[j]);
		}//endfor j
		InternalTrLP.push_back(LP);
	}//

		Init();

	};//end ScoreFollower
	~ScoreFollower(){};

	void SetTPQN(int TPQN){
		TPQN_=TPQN;
		Init();
	};//end SetTPQN

	void Init(){

		isFirst_=true;
		currentState_=0;
		previousState_=-1;
		tickPerSec_=initialTickPerSec_;
		tempo_.clear();
		tempo_.push_back(tickPerSec_);
		M_=pow(0.2/tickPerSec_,2.);
		Sig_t=pow(0.014,2.);//
		Sig_v=pow(0.03/(tickPerSec_*TPQN_),2.);
		SwSig_t[0]=Sig_t;
		SwSig_t[1]=pow(0.16,2.);
		LPLambda_[0]=log(0.95);
		LPLambda_[1]=log(0.05);
		LPSwitch_.resize(2);
		LPSwitch_[0]=log(0.95);
		LPSwitch_[1]=log(0.05);
		SwSecPerTick_[0]=1./tickPerSec_;
		SwSecPerTick_[1]=1./tickPerSec_;
		SwM_[0]=M_;
		SwM_[1]=M_;

		like_[0]=log(0.9);
		for(int i=1;i<nState_;i+=1){like_[i]=log(0.1/(nState_-1));}//endfor i

		D1_=3; D2_=2;
		vector<double> evtProb(D1_+D2_+1);//-D1,...,D2
		TopTrLP.assign(D1_+D2_+1,-100);
		double gammabar;
{
		int da;
		double prob;
		double sum=0;
		string str;

		da=-2; prob=0.00516;
		evtProb[da+D1_]=prob; TopTrLP[da+D1_]=log(prob);
		da=-1; prob=0.00886;
		evtProb[da+D1_]=prob; TopTrLP[da+D1_]=log(prob);
		da=0; prob=0.01342;
		evtProb[da+D1_]=prob; TopTrLP[da+D1_]=log(prob);
		da=1; prob=0.94531;
		evtProb[da+D1_]=prob; TopTrLP[da+D1_]=log(prob);
		da=2; prob=0.00610;
		evtProb[da+D1_]=prob; TopTrLP[da+D1_]=log(prob);
		da=3; prob=0.00073;
		sum=0.00516+0.00886+0.01342+0.94531+0.00610+0.00073;

		gammabar=(1-sum)/nState_;
//		logTrSkipLP=log(gammabar);
//		logTrSkipLP=-20;//online
		logTrSkipLP=-40;//offline
}//

		pitchDiffProb_.clear();
		pitchDiffProb_.assign(256,1E-20);
		pitchDiffProb_[0+128]=0.95;
		pitchDiffProb_[2+128]=0.15/2.;
		pitchDiffProb_[-2+128]=0.15/2.;
		pitchDiffProb_[1+128]=0.22/2.;
		pitchDiffProb_[-1+128]=0.22/2.;
		pitchDiffProb_[12+128]=0.0047/2.;
		pitchDiffProb_[-12+128]=0.0047/2.;
		for(int j=-11;j<=11;j+=1){
			if(0.0002>pitchDiffProb_[j+128]){pitchDiffProb_[j+128]=0.0002;}
		}//endfor j
		Norm(pitchDiffProb_);

	};//end Init

	void Update(Observation& observed, double time){
		timeHist.push_back(time);
		if(isFirst_){
			UpdateLike_init(observed);
			isFirst_=false;
			currentOnsetTime_=time;
			previousOnsetTime_=currentOnsetTime_;
		}else{
			previousState_=currentState_;
			UpdateLike(observed,time);
		}//endif

		currentState_=GetOptimalState();
		if(currentState_!=previousState_){
			previousOnsetTime_=currentOnsetTime_;
			currentOnsetTime_=time;
		}//endif
		UpdateTickPerSec(time);
	};//end Update

	double UpdateTickPerSec(double time){
		double ioi=time-previousOnsetTime_;//effective ioi (state-onset-time-interval)

	////////////////////// moving average
	/*
		const unsigned int range=4;
		if(currentState_>0 && currentState_==previousState_+1 && ioi>0.035
		    && Type[currentState_]=="CH" && Type[currentState_-1]=="CH"){
			double tempo=((Stime[currentState_]-Stime[currentState_-1])/ioi);
			tempo_.push_back(tempo);
			if(tempo_.size()>range){tempo_.erase(tempo_.begin());}
			lastTickPerSec_=tempo_[tempo_.size()-1];
			tickPerSec_=0.;
			for(int i=0;i<tempo_.size();i+=1){tickPerSec_+=tempo_[i];}
			tickPerSec_/=tempo_.size();
		}//endif
	*/
	////////////////////// (simple) Kalman filter
	/*
		if(currentState_>0 && currentState_==previousState_+1 && ioi>0.035
		    && Type[currentState_]=="CH" && Type[currentState_-1]=="CH"){
			double secPerTick=1/tickPerSec_;
			double nu=double(Stime[currentState_]-Stime[currentState_-1]);
			double K=nu*M_/(nu*nu*M_+Sig_t);
			secPerTick+=K*(ioi-secPerTick*nu);
			tickPerSec_=1./secPerTick;
			M_=(Sig_t*M_)/(nu*nu*M_+Sig_t)+nu*nu*Sig_v;
		}//endif
	*/
	////////////////////// switching Kalman filter

		if(currentState_>0 && currentState_==previousState_+1 && ioi>0.035
		    && Type[currentState_]=="CH" && Type[currentState_-1]=="CH"){
			double nu=double(Stime[currentState_]-Stime[currentState_-1]);
			double SwK[2][2];
			double SwTmpPredSecPerTick[2][2];
			double SwDelta[2][2];
			vector<double> tmpLPSwitch(4);//2*s_{m-1}+s_m=2*r+s
			for(int r=0;r<2;r+=1)for(int s=0;s<2;s+=1){
				SwK[r][s]=nu*SwM_[r]/(nu*nu*SwM_[r]+SwSig_t[s]);
				SwTmpPredSecPerTick[r][s]=SwSecPerTick_[r]+SwK[r][s]*(ioi-nu*SwSecPerTick_[r]);
				SwDelta[r][s]=(1-SwK[r][s]*nu)*SwM_[r];
				tmpLPSwitch[2*r+s]=LPLambda_[s]+LPSwitch_[r]-0.5*log(2*M_PI*(nu*nu*SwM_[r]+SwSig_t[s]))-0.5*pow(ioi-nu*SwSecPerTick_[r],2.)/(nu*nu*SwM_[r]+SwSig_t[s]);
			}//endfor r,s
			Lognorm(tmpLPSwitch);
			for(int s=0;s<2;s+=1){
				SwSecPerTick_[s]=(exp(tmpLPSwitch[s])*SwTmpPredSecPerTick[0][s]+exp(tmpLPSwitch[2+s])*SwTmpPredSecPerTick[1][s])/(exp(tmpLPSwitch[s])+exp(tmpLPSwitch[2+s]));
				SwM_[s]=(exp(tmpLPSwitch[s])*(SwDelta[0][s]+pow(SwSecPerTick_[s]-SwTmpPredSecPerTick[0][s],2.))
				+exp(tmpLPSwitch[2+s])*(SwDelta[1][s]+pow(SwSecPerTick_[s]-SwTmpPredSecPerTick[1][s],2.)))
				/(exp(tmpLPSwitch[s])+exp(tmpLPSwitch[2+s]));
				SwM_[s]+=nu*nu*Sig_v;
				LPSwitch_[s]=LogAdd(tmpLPSwitch[s],tmpLPSwitch[2+s]);
			}//endfor s
			Lognorm(LPSwitch_);
			tickPerSec_=1./(SwSecPerTick_[0]*exp(LPSwitch_[0])+SwSecPerTick_[1]*exp(LPSwitch_[1]));
		}//endif

		assert(tickPerSec_>0);
		if(currentState_<nState_-1){
			predictedNextTime_=time+(Stime[currentState_+1]-Stime[currentState_])/tickPerSec_;
		}else{
			predictedNextTime_=time+1;
		}//endif
		return tickPerSec_;
	}//end UpdateTickPerSec

	void UpdateLike_init(Observation& observed){
		vector<int> vi(like_.size());
		for(int i=0;i<nState_;i+=1){
			like_[i]+=PitchLP[i][observed.pitch];
			vi[i]=i;
		}//endfor i
		amaxHist_.push_back(vi);
		inputPitch_.push_back(observed.pitch);
	}//end UpdateLike_init

	void UpdateLike(Observation& observed,double time){
		vector<double> prev_like(like_);
		vector<int> vi(like_.size());
		double ioi=observed.ioi;
		double BIoiStr[4];
		double sig;
		double mu;

		sig=0.3333;
		double LogBIoiInsertion=log((2.*sig/M_PI)/(pow(ioi-0.5,2.)+pow(sig,2.)));
		double BIoiInsertion=(sig/M_PI)/(pow(ioi-0.5,2.)+pow(sig,2.));
		double LogBIoiSkip=log((sig/M_PI)/(pow(ioi-0.5,2.)+pow(sig,2.)));

		sig=0.01; mu=0; BIoiStr[0]=0.995*(1./sig)*exp(-(ioi-mu)/sig)+0.005*BIoiInsertion;//chordal
		sig=0.05; mu=0.05; BIoiStr[1]=0.95*1./sqrt(2*M_PI*sig*sig)*exp(-0.5*pow((ioi-mu)/sig,2.))+0.05*BIoiInsertion;//arp
		sig=0.07; mu=0.13; BIoiStr[2]=0.95*1./sqrt(2*M_PI*sig*sig)*exp(-0.5*pow((ioi-mu)/sig,2.))+0.05*BIoiInsertion;//app
		sig=0.015; mu=0.082; BIoiStr[3]=0.95*1./sqrt(2*M_PI*sig*sig)*exp(-0.5*pow((ioi-mu)/sig,2.))+0.05*BIoiInsertion;//tr

		for(int i=0;i<nState_;i+=1){
			// self transition
			int am=i;
			double max=prev_like[i];
			max+=log( exp(InternalTrLP[TopId[i]][BotId[i]][BotId[i]])*(IOIWeight[i][0]*BIoiStr[0]+IOIWeight[i][1]*BIoiStr[1]+IOIWeight[i][2]*BIoiStr[2]+IOIWeight[i][3]*BIoiStr[3])
			         + exp(TopTrLP[D1_]+InternalTrLP[TopId[i]][BotId[i]][101]+InternalTrLP[TopId[i]][0][BotId[i]])*BIoiInsertion );

			double logprob;
			// forward transition
			for(int j=i-1;j>=0&&j>=i-12;j-=1){
				if(TopId[i]-TopId[j]>D2_){continue;}
				if(TopId[i]==TopId[j]){//if the transition is internal
					logprob=prev_like[j]+InternalTrLP[TopId[i]][BotId[j]][BotId[i]]+log(0.95*BIoiStr[2]+0.05*BIoiInsertion);
				}else if(Stime[TopId[i]]==EndStime[TopId[j]]){//if the transition is immediate (iost=0)
					logprob=prev_like[j]+TopTrLP[D1_+TopId[i]-TopId[j]]+InternalTrLP[TopId[j]][BotId[j]][101]+InternalTrLP[TopId[i]][0][BotId[i]]
							+log(0.95*BIoiStr[2]+0.05*BIoiInsertion);
				}else{
					sig=0.5+(Stime[TopId[i]]-EndStime[TopId[j]])*0.2/TPQN_;
					mu=(Stime[TopId[i]]-EndStime[TopId[j]])/tickPerSec_-stolenTime[j];
					double ioi2=time-previousOnsetTime_;
					if(mu<0){mu=0;}
					logprob=prev_like[j]+TopTrLP[D1_+TopId[i]-TopId[j]]+InternalTrLP[TopId[j]][BotId[j]][101]+InternalTrLP[TopId[i]][0][BotId[i]]
//							+log((0.4/M_PI)/(pow(ioi-mu,2.)+pow(0.4,2.)));//online
							+log((0.3/M_PI)/(pow(ioi-mu,2.)+pow(0.3,2.)));//offline
				}//endif
				if(logprob>max){max=logprob;am=j;}
			}//endfor j

			// backward transition
			for(int j=i+1;j<=i+18&&j<nState_;j+=1){
				if(TopId[j]-TopId[i]>D1_){continue;}
				logprob=prev_like[j]+TopTrLP[D1_+TopId[i]-TopId[j]]+InternalTrLP[TopId[j]][BotId[j]][101]+InternalTrLP[TopId[i]][0][BotId[i]]
						+((ioi>0.3)? LogBIoiInsertion:-10);
				if(logprob>max){max=logprob;am=j;}
			}//endfor j

			// large skip
			logprob=prev_like[currentState_]+logTrSkipLP+InternalTrLP[TopId[currentState_]][BotId[currentState_]][101]+InternalTrLP[TopId[i]][0][BotId[i]]
			+((ioi>0.3)? LogBIoiSkip:-20);
			if(logprob>max){max=logprob; am=currentState_;}

			// update
			like_[i]=max+PitchLP[i][observed.pitch];
			vi[i]=am;
		}//endfor i
		amaxHist_.push_back(vi);
		inputPitch_.push_back(observed.pitch);
	}//end UpdateLike

	int GetOptimalState(){
		double max=like_[0];
		int amax=0;
		for(int i=1;i<like_.size();i+=1){
			if(like_[i]>max){amax=i; max=like_[i];}//endif
		}//endfor i
		return amax;
	}//end GetOptimalState

	int GetCurrentTick() const{
		assert(currentState_<nState_);
		return Stime[currentState_];
	}//end GetCurrentTick

	double GetTickPerSec() const {
		return tickPerSec_;
	}//end GetTickPerSec

	double GetLastTickPerSec() const {
		return lastTickPerSec_; 
	}//end GetLastTickPerSec

	int GetCurrentState() const {
		return currentState_;
	}//end GetCurrentState

	void HistWrite(string filename){
	}//end HistWrite

	double GetPredictedTime(){
		return predictedNextTime_;
	}//end GetPredictedTime

	string GetFmt1ID(int hmmPos,int pitch){
		string tmps;
		int amax=0;
		double max=pitchDiffProb_[pitch-pitchList_[hmmPos][0]+128];
		for(int j=0;j<pitchList_[hmmPos].size();j+=1){
			if(pitchDiffProb_[pitch-pitchList_[hmmPos][j]+128]>max){
				max=pitchDiffProb_[pitch-pitchList_[hmmPos][j]+128];
				amax=j;
			}//endif
		}//endfor j
		tmps=scorePosList_[hmmPos][amax];
		for(int i=0;i<hmm.duplicateOnsets.size();i+=1){
			for(int j=1;j<hmm.duplicateOnsets[i].numOnsets;j+=1){
				if(tmps==hmm.duplicateOnsets[i].fmt1IDs[j]){
					tmps=hmm.duplicateOnsets[i].fmt1IDs[0];
					break;
				}//endif
			}//endfor j
		}//endfor i
		return tmps;
	}//end GetFmt1ID
	
	string GetCorrectSitch(int hmmPos,string fmt1ID){
		string out="";
		for(int i=0;i<hmm.evts[hmmPos].fmt1IDsPerCluster.size();i+=1){
			for(int j=0;j<hmm.evts[hmmPos].fmt1IDsPerCluster[i].size();j+=1){
				if(fmt1ID==hmm.evts[hmmPos].fmt1IDsPerCluster[i][j]){
					out=hmm.evts[hmmPos].sitchesPerCluster[i][j];
					break;
				}//endif
			}//endfor j
			if(out!=""){break;}
		}//endfor i
		return out;
	}//end GetCorrectSitch

	ScorePerfmMatch GetMatchResult(PianoRoll pr){
		ScorePerfmMatch match;
		ScorePerfmMatchEvt evt;
		Observation obs;
		isFirst_=true;

		/// Initialise
		obs.pitch=pr.evts[0].pitch;
		obs.ioi=pr.evts[0].ontime;
		Update(obs,pr.evts[0].ontime);
		evt.ID=pr.evts[0].ID;
		evt.ontime=pr.evts[0].ontime;
		evt.offtime=pr.evts[0].offtime;
		evt.sitch=pr.evts[0].sitch;
		evt.onvel=pr.evts[0].onvel;
		evt.offvel=pr.evts[0].offvel;
		evt.channel=pr.evts[0].channel;
		evt.matchStatus=0;
		evt.errorInd=0;
		evt.skipInd="0";
		match.evts.push_back(evt);

		/// Viterbi updates
		for(int n=1;n<pr.evts.size();n+=1){
			obs.pitch=pr.evts[n].pitch;
			obs.ioi=pr.evts[n].ontime-pr.evts[n-1].ontime;
			Update(obs,pr.evts[n].ontime);
			evt.ID=pr.evts[n].ID;
			evt.ontime=pr.evts[n].ontime;
			evt.offtime=pr.evts[n].offtime;
			evt.sitch=pr.evts[n].sitch;
			evt.onvel=pr.evts[n].onvel;
			evt.offvel=pr.evts[n].offvel;
			evt.channel=pr.evts[n].channel;
			evt.matchStatus=0;
			evt.errorInd=0;
			evt.skipInd="-";
			match.evts.push_back(evt);
		}//endfor n

		/// Backtracking
		vector<int> stateSeq(pr.evts.size());
		stateSeq[stateSeq.size()-1]=GetOptimalState();
		for(int n=stateSeq.size()-2;n>=0;n-=1){
			stateSeq[n]=amaxHist_[n+1][stateSeq[n+1]];
		}//endfor n

		string correctSitch;
		for(int n=0;n<pr.evts.size();n+=1){
			match.evts[n].stime=Stime[stateSeq[n]];
			match.evts[n].fmt1ID=GetFmt1ID(stateSeq[n],pr.evts[n].pitch);
			correctSitch=GetCorrectSitch(stateSeq[n],match.evts[n].fmt1ID);
			if(correctSitch==""){continue;}
			if(SitchToPitch(correctSitch)==SitchToPitch(match.evts[n].sitch)){
				match.evts[n].sitch=correctSitch;
			}//endif
		}//endfor n

		return match;
	}//end GetMatchResult

};//endclass ScoreFollower




