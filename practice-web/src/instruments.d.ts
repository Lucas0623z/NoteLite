export type InstrumentVariant = { id: string; name: string; transpose: number };
export type InstrumentProfile = { id: string; name: string; minMidi: number; maxMidi: number; minHz: number; maxHz: number; windowSize: number; defaultVariant: string; variants: readonly InstrumentVariant[]; input: string; recommendedInput: string };
export const INSTRUMENT_PROFILES: readonly InstrumentProfile[];
export function resolveProfile(id: string | { id?: string; profileId?: string }): InstrumentProfile;
export function resolveInstrument(part: object, selected?: string, options?: { variant?: string; transpose?: number }): { profile: InstrumentProfile; name: string; source: string; reliable: boolean; manual: boolean; variant: string; transpose: number };
export function soundingMidi(note: { midi: number; transposeExplicit?: boolean }, instrument: { transpose?: number }): number;
