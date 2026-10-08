"""Score-independent acoustic evidence for same-pitch re-articulation.

Model/onset-detector peaks are candidates. A new attack requires a local energy
valley followed by a rapid rise, a quiet-to-voiced rise, or a clear fast transient.
The envelope reference is local to the previous accepted attack; a stale louder
note cannot manufacture a delayed second attack. No expected pitches are read.
"""
import copy
import math
import numpy as np


class AcousticOnsets:
    def __init__(self,audio,rate):
        self.audio=np.asarray(audio,dtype=np.float64);self.rate=rate;self.cache={}

    def envelope(self,frequency):
        # Two periods avoid treating low-frequency waveform cycles as attacks.
        window=max(round(self.rate*.01),round(2*self.rate/max(20,frequency)))
        window=min(window,round(self.rate*.08));window=max(2,window)
        if window not in self.cache:
            hop=max(1,round(self.rate*.005));centers=np.arange(0,len(self.audio),hop)
            integral=np.concatenate(([0.],np.cumsum(self.audio**2)))
            left=np.maximum(0,centers-window//2);right=np.minimum(len(self.audio),centers+window//2)
            energy=np.sqrt((integral[right]-integral[left])/np.maximum(1,right-left))
            self.cache[window]=(centers/self.rate,energy)
        return self.cache[window]

    def evaluate(self,time,last_attack=None,frequency=261.63,lookback=.035):
        times,rms=self.envelope(frequency)
        evidence={'candidateOnset':round(float(time),6),'accepted':False,'reason':'insufficient-acoustic-reattack-evidence'}
        if last_attack is not None and time-last_attack<.08:
            return evidence|{'reason':'attack-refractory-period'}
        best=None
        for index in np.flatnonzero((times>=time-lookback)&(times<=time+.035)):
            center=float(times[index])
            if last_attack is not None and center-last_attack<.08:continue
            start=max(center-.08,(last_attack+.02) if last_attack is not None else 0)
            baseline=rms[(times>=start)&(times<center-.025)]
            valley=rms[(times>=max(start,center-.025))&(times<=center)]
            previous=rms[(times>=max(start,center-.015))&(times<center-.005)]
            following=rms[(times>=center+.005)&(times<=center+.025)]
            if not len(valley) or not len(previous) or not len(following):continue
            reference=float(np.quantile(baseline,.8)) if len(baseline) else float(np.max(valley))
            bottom=float(np.min(valley));before=float(np.median(previous));after=float(np.median(following))
            rise=after/max(bottom,1e-6);fast=after/max(before,1e-6);depth=bottom/max(reference,1e-6)
            reason=None
            if after>=.008 and reference>=.008 and depth<.68 and rise>=2 and fast>=1.35:
                reason='energy-valley-and-rapid-rise'
            elif after>=.008 and bottom<.004 and fast>=1.8:
                reason='quiet-to-voiced-rapid-rise'
            elif after>=.014 and fast>=2.5:
                reason='clear-fast-energy-transient'
            quality=fast if reason else min(fast,2.5)*min(rise,2)
            metrics={'acousticOnset':round(center,6),'valleyDepth':round(depth,4),'valleyRiseRatio':round(rise,4),
                     'fastRiseRatio':round(fast,4),'postRms':round(after,6)}
            if best is None or (reason is not None,quality)>best[0]:
                best=((reason is not None,quality),metrics,reason)
        if best:
            evidence.update(best[1])
            if best[2]:evidence.update(accepted=True,reason=best[2])
        return evidence


def gate_candidates(audio,rate,candidates,times,frequency):
    acoustic=AcousticOnsets(audio,rate);accepted=[];proof=[];last=None
    for candidate in sorted(float(t) for t in candidates):
        nearby=np.asarray(frequency)[np.abs(np.asarray(times)-candidate)<=.05]
        nearby=nearby[np.isfinite(nearby)&(nearby>0)]
        nominal=float(np.median(nearby)) if len(nearby) else 261.63
        evidence=acoustic.evaluate(candidate,last,nominal);proof.append(evidence)
        if evidence['accepted']:
            accepted.append(candidate);last=evidence['acousticOnset']
    return accepted,proof


def merge_basic_pitch(notes,audio,rate):
    acoustic=AcousticOnsets(audio,rate);raw=copy.deepcopy(notes);result=[];previous={};proof=[];merged=[]
    for index,original in enumerate(notes):
        note=copy.deepcopy(original);key=note.get('modelMidi',note['midi']);prior=previous.get(key)
        frequency=440*2**((key-69)/12)
        previous_attack=prior['onsetEvidence'].get('acousticOnset',prior['onset']) if prior is not None else None
        # AMT attack estimates can lag a soft attack; use actual acoustic time
        # for refractory history while retaining the model's original timestamp.
        evidence=acoustic.evaluate(note['onset'],previous_attack,frequency,lookback=.09)
        evidence['rawNoteIndex']=index;proof.append(evidence)
        note['rawNoteIndices']=[index];note['onsetEvidence']=evidence
        if prior is not None:
            gap=note['onset']-(prior['onset']+prior['duration'])
            if -.03<=gap<=.04 and not evidence['accepted']:
                end=max(prior['onset']+prior['duration'],note['onset']+note['duration'])
                total=prior['duration']+note['duration']
                prior['confidence']=(prior['confidence']*prior['duration']+note['confidence']*note['duration'])/total
                prior['duration']=round(end-prior['onset'],6)
                prior['pitchBendCents']=prior.get('pitchBendCents',[])+note.get('pitchBendCents',[])
                prior['rawNoteIndices'].append(index);prior['confidenceAggregation']='duration-weighted-mean'
                prior.setdefault('suppressedReattackEvidence',[]).append(evidence)
                merged.append({'intoRawNoteIndex':prior['rawNoteIndices'][0],'rawNoteIndex':index,'evidence':evidence})
                continue
            if not evidence['accepted']:
                note.update(reviewRequired=True,onsetReliable=False,reviewReason='unconfirmed-same-pitch-reattack')
        if prior is not None:note.setdefault('onsetReliable',evidence['accepted'])
        result.append(note);previous[key]=note
    return result,raw,{'method':'waveform-onset-evidence-v1','rawNoteCount':len(raw),'noteCount':len(result),
                       'rawNotesPreserved':True,'mergedSamePitchFragments':merged,'candidateOnsets':proof,
                       'thresholds':{'refractorySeconds':.08,'adjacentGapSeconds':.04,'valleyBelowReference':.68,
                                     'valleyRiseRatio':2,'fastRiseRatio':1.35,'clearTransientRiseRatio':2.5},
                       'limits':'Flat-energy same-pitch re-articulations with no clear transient can remain unconfirmed.'}
