import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { instrumentForCourse, summarizeHistory, useYinban } from "./runtime";
import { ConnectedScoresPage, ConnectedHistoryPage } from "./integration";
import aiIcon from "../imports/image.png";
import scoresUploadNormal from "../imports/my-scores-upload-normal.png";
import scoresUploadPressed from "../imports/my-scores-upload-pressed.png";
import tuningForkDisc from "../imports/01-tuning-fork.svg";
import metronomeDisc from "../imports/02-metronome.svg";
import headphonesDisc from "../imports/03-headphones.svg";
import batonDisc from "../imports/04-baton.svg";
import lyreDisc from "../imports/05-lyre.svg";
import triangleDisc from "../imports/06-triangle.svg";
import secondTuningForkDisc from "../imports/01-tuning-fork-1.svg";
import secondMetronomeDisc from "../imports/02-metronome-1.svg";
import secondHeadphonesDisc from "../imports/03-headphones-1.svg";
import secondBatonDisc from "../imports/04-baton-1.svg";
import secondLyreDisc from "../imports/05-lyre-1.svg";
import secondTriangleDisc from "../imports/06-triangle-1.svg";
import brickRecordPlayer from "../imports/01-brick.svg";
import goldRecordPlayer from "../imports/02-gold.svg";
import tealRecordPlayer from "../imports/03-teal.svg";
import thirdTuningForkDisc from "../imports/01-tuning-fork-2.svg";
import thirdMetronomeDisc from "../imports/02-metronome-2.svg";
import thirdHeadphonesDisc from "../imports/03-headphones-2.svg";
import thirdBatonDisc from "../imports/04-baton-2.svg";
import thirdLyreDisc from "../imports/05-lyre-2.svg";
import thirdTriangleDisc from "../imports/06-triangle-2.svg";
import fourthTuningForkDisc from "../imports/01-tuning-fork-3.svg";
import fourthMetronomeDisc from "../imports/02-metronome-3.svg";
import fourthHeadphonesDisc from "../imports/03-headphones-3.svg";
import fourthBatonDisc from "../imports/04-baton-3.svg";
import fourthLyreDisc from "../imports/05-lyre-3.svg";
import fourthTriangleDisc from "../imports/06-triangle-3.svg";
import sageRecordPlayer from "../imports/05-sage.svg";
import navyRecordPlayer from "../imports/04-navy-1.svg";
import fifthTuningForkDisc from "../imports/01-tuning-fork-4.svg";
import fifthMetronomeDisc from "../imports/02-metronome-4.svg";
import fifthHeadphonesDisc from "../imports/03-headphones-4.svg";
import fifthBatonDisc from "../imports/04-baton-4.svg";
import fifthLyreDisc from "../imports/05-lyre-4.svg";
import fifthTriangleDisc from "../imports/06-triangle-4.svg";
import sixthTuningForkDisc from "../imports/01-tuning-fork-5.svg";
import sixthMetronomeDisc from "../imports/02-metronome-5.svg";
import sixthHeadphonesDisc from "../imports/03-headphones-5.svg";
import sixthBatonDisc from "../imports/04-baton-5.svg";
import sixthLyreDisc from "../imports/05-lyre-5.svg";
import sixthTriangleDisc from "../imports/06-triangle-5.svg";
import oliveRecordPlayer from "../imports/06-olive.svg";
import roseRecordPlayer from "../imports/07-rose-1.svg";
import plumRecordPlayer from "../imports/08-plum.svg";
import seventhTuningForkDisc from "../imports/01-tuning-fork-6.svg";
import seventhMetronomeDisc from "../imports/02-metronome-6.svg";
import seventhHeadphonesDisc from "../imports/03-headphones-6.svg";
import seventhBatonDisc from "../imports/04-baton-6.svg";
import seventhLyreDisc from "../imports/05-lyre-6.svg";
import seventhTriangleDisc from "../imports/06-triangle-6.svg";
import eighthTuningForkDisc from "../imports/01-tuning-fork-8.svg";
import eighthMetronomeDisc from "../imports/02-metronome-8.svg";
import eighthHeadphonesDisc from "../imports/03-headphones-8.svg";
import eighthBatonDisc from "../imports/04-baton-8.svg";
import eighthLyreDisc from "../imports/05-lyre-8.svg";
import eighthTriangleDisc from "../imports/06-triangle-8.svg";
import ninthTuningForkDisc from "../imports/01-tuning-fork-9.svg";
import ninthMetronomeDisc from "../imports/02-metronome-9.svg";
import ninthHeadphonesDisc from "../imports/03-headphones-9.svg";
import ninthBatonDisc from "../imports/04-baton-9.svg";
import ninthLyreDisc from "../imports/05-lyre-9.svg";
import ninthTriangleDisc from "../imports/06-triangle-9.svg";
import lavenderRecordPlayer from "../imports/09-lavender.svg";
import blueRecordPlayer from "../imports/10-blue.svg";
import tenthTuningForkDisc from "../imports/01-tuning-fork-10.svg";
import tenthMetronomeDisc from "../imports/02-metronome-10.svg";
import tenthHeadphonesDisc from "../imports/03-headphones-10.svg";
import tenthBatonDisc from "../imports/04-baton-10.svg";
import tenthLyreDisc from "../imports/05-lyre-10.svg";
import tenthTriangleDisc from "../imports/06-triangle-10.svg";
import eleventhTuningForkDisc from "../imports/01-tuning-fork-11.svg";
import eleventhMetronomeDisc from "../imports/02-metronome-11.svg";
import eleventhHeadphonesDisc from "../imports/03-headphones-11.svg";
import eleventhBatonDisc from "../imports/04-baton-11.svg";
import eleventhLyreDisc from "../imports/05-lyre-11.svg";
import eleventhTriangleDisc from "../imports/06-triangle-11.svg";
import twelfthTuningForkDisc from "../imports/01-tuning-fork-12.svg";
import twelfthMetronomeDisc from "../imports/02-metronome-12.svg";
import twelfthHeadphonesDisc from "../imports/03-headphones-12.svg";
import twelfthBatonDisc from "../imports/04-baton-12.svg";
import twelfthLyreDisc from "../imports/05-lyre-12.svg";
import twelfthTriangleDisc from "../imports/06-triangle-12.svg";
import ochreRecordPlayer from "../imports/11-ochre.svg";
import sandRecordPlayer from "../imports/12-sand.svg";
import brickBanner from "../imports/01-brick-1.svg";
import goldBanner from "../imports/02-gold-1.svg";
import tealBanner from "../imports/03-teal-1.svg";
import navyBanner from "../imports/04-navy-2.svg";
import sageBanner from "../imports/05-sage-1.svg";
import oliveBanner from "../imports/06-olive-1.svg";
import roseBanner from "../imports/07-rose-2.svg";
import plumBanner from "../imports/08-plum-1.svg";
import lavenderBanner from "../imports/09-lavender-1.svg";
import blueBanner from "../imports/10-blue-1.svg";
import ochreBanner from "../imports/11-ochre-1.svg";
import sandBanner from "../imports/12-sand-1.svg";
import sunIcon from "../imports/01-sun-dark.png";
import moonIcon from "../imports/02-moon-light.png";
import outfitDarkIcon from "../imports/03-outfit-dark.png";
import outfitLightIcon from "../imports/03-outfit-light.png";
import settingsDarkIcon from "../imports/04-settings-gear-dark.png";
import settingsLightIcon from "../imports/04-settings-gear-light.png";
import qrDarkIcon from "../imports/01-qr-dark.png";
import qrLightIcon from "../imports/01-qr-light.png";
import experienceDarkIcon from "../imports/03-experience-bolt-dark.png";
import experienceLightIcon from "../imports/03-experience-bolt-light.png";
import leaderboardDarkIcon from "../imports/04-leaderboard-trophy-dark.png";
import leaderboardLightIcon from "../imports/04-leaderboard-trophy-light.png";
import checkinDarkIcon from "../imports/05-checkin-medal-dark.png";
import checkinLightIcon from "../imports/05-checkin-medal-light.png";
import myScoresDarkIcon from "../imports/01-my-scores-dark.png";
import myScoresLightIcon from "../imports/01-my-scores-light.png";
import officialScoresDarkIcon from "../imports/02-official-scores-dark.png";
import officialScoresLightIcon from "../imports/02-official-scores-light.png";
import practiceHistoryDarkIcon from "../imports/03-practice-record-dark.png";
import practiceHistoryLightIcon from "../imports/03-practice-record-light.png";
import accountTabDarkIcon from "../imports/04-account-cat-dark.png";
import accountTabLightIcon from "../imports/04-account-cat-light.png";
import accountLightIcon from "../imports/account-cat.svg";
import musicNoteIcon from "../imports/music-note.png";
import violinCourse from "../imports/01-violin.png";
import violaCourse from "../imports/02-viola.png";
import celloCourse from "../imports/03-cello.png";
import doubleBassCourse from "../imports/04-double-bass.png";
import harpCourse from "../imports/05-harp.png";
import pianoCourse from "../imports/06-piano.png";
import fluteCourse from "../imports/07-flute.png";
import clarinetCourse from "../imports/08-clarinet.png";
import bassoonCourse from "../imports/09-bassoon.png";
import oboeCourse from "../imports/10-oboe.png";
import frenchHornCourse from "../imports/11-french-horn.png";
import trumpetCourse from "../imports/12-trumpet.png";
import tromboneCourse from "../imports/13-trombone.png";
import tubaCourse from "../imports/14-tuba.png";
import euphoniumCourse from "../imports/15-euphonium.png";
import bachOutfit from "../imports/01-bach.png";
import mozartOutfit from "../imports/02-mozart.png";
import beethovenOutfit from "../imports/03-beethoven.png";
import schubertOutfit from "../imports/04-schubert.png";
import chopinOutfit from "../imports/05-chopin.png";
import lisztOutfit from "../imports/06-liszt.png";
import tchaikovskyOutfit from "../imports/07-tchaikovsky.png";
import debussyOutfit from "../imports/08-debussy.png";
import rachmaninoffOutfit from "../imports/09-rachmaninoff.png";
import claraSchumannOutfit from "../imports/10-clara-schumann.png";
import bachCat from "../imports/01-bach-cat.png";
import mozartCat from "../imports/02-mozart-cat.png";
import beethovenCat from "../imports/03-beethoven-cat.png";
import schubertCat from "../imports/04-schubert-cat.png";
import chopinCat from "../imports/05-chopin-cat.png";
import lisztCat from "../imports/06-liszt-cat.png";
import tchaikovskyCat from "../imports/07-tchaikovsky-cat.png";
import debussyCat from "../imports/08-debussy-cat.png";
import rachmaninoffCat from "../imports/09-rachmaninoff-cat.png";
import claraSchumannCat from "../imports/10-clara-schumann-cat.png";

const wardrobeOutfits: { id: string; label: string; image?: string; practiceExclusive?: boolean }[] = [
  { id: "plain", label: "无装扮" },
  { id: "bach", label: "巴赫", image: bachOutfit },
  { id: "mozart", label: "莫扎特", image: mozartOutfit },
  { id: "beethoven", label: "贝多芬", image: beethovenOutfit },
  { id: "schubert", label: "舒伯特", image: schubertOutfit },
  { id: "chopin", label: "肖邦", image: chopinOutfit },
  { id: "liszt", label: "李斯特", image: lisztOutfit },
  { id: "tchaikovsky", label: "柴可夫斯基", image: tchaikovskyOutfit },
  { id: "debussy", label: "德彪西", image: debussyOutfit },
  { id: "rachmaninoff", label: "拉赫玛尼诺夫", image: rachmaninoffOutfit },
  { id: "clara-schumann", label: "克拉拉·舒曼", image: claraSchumannOutfit },
  { id: "bach-cat", label: "猫赫", image: bachCat, practiceExclusive: true },
  { id: "mozart-cat", label: "莫扎猫", image: mozartCat, practiceExclusive: true },
  { id: "beethoven-cat", label: "猫多芬", image: beethovenCat, practiceExclusive: true },
  { id: "schubert-cat", label: "猫伯特", image: schubertCat, practiceExclusive: true },
  { id: "chopin-cat", label: "肖猫", image: chopinCat, practiceExclusive: true },
  { id: "liszt-cat", label: "猫斯特", image: lisztCat, practiceExclusive: true },
  { id: "tchaikovsky-cat", label: "猫可夫斯基", image: tchaikovskyCat, practiceExclusive: true },
  { id: "debussy-cat", label: "德猫西", image: debussyCat, practiceExclusive: true },
  { id: "rachmaninoff-cat", label: "拉赫猫尼诺夫", image: rachmaninoffCat, practiceExclusive: true },
  { id: "clara-schumann-cat", label: "克猫猫·舒曼", image: claraSchumannCat, practiceExclusive: true },
];

const pressFeedback = "touch-manipulation transition-[transform,border-width] duration-75 enabled:active:translate-y-[3px] enabled:active:border-b-2 motion-reduce:transition-none [-webkit-tap-highlight-color:transparent]";

function useAnimatedSheet(initialOpen = false) {
  const [open, setOpen] = useState(initialOpen);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closingAnimation = useRef<Animation | null>(null);
  const closing = useRef(false);
  useEffect(() => () => { closingAnimation.current?.cancel(); }, []);
  const changeOpen = (nextOpen: boolean) => {
    const dialog = dialogRef.current;
    if (nextOpen) {
      closing.current = false;
      closingAnimation.current?.cancel();
      closingAnimation.current = null;
      if (dialog) delete dialog.dataset.closing;
      setOpen(true);
      return;
    }
    if (!dialog?.open || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      dialog?.close();
      setOpen(false);
      return;
    }
    if (closing.current) return;
    closing.current = true;
    dialog.dataset.closing = "true";
    const animation = dialog.animate([
      { transform: getComputedStyle(dialog).transform },
      { transform: "translateY(-100%)" },
    ], { duration: 260, easing: "cubic-bezier(0.4, 0, 0.8, 0.2)", fill: "forwards" });
    closingAnimation.current = animation;
    animation.finished.then(() => {
      if (closingAnimation.current === animation) {
        closing.current = false;
        dialog.close();
        setOpen(false);
      }
    }).catch(() => {});
  };
  return [open, changeOpen, dialogRef] as const;
}

function StreakNote({ active, isDark = false, className }: { active: boolean; isDark?: boolean; className: string }) {
  return <img src={musicNoteIcon} alt="" className={`${className} object-contain ${active ? "" : `grayscale opacity-60 ${isDark ? "brightness-100" : "brightness-[0.65]"}`}`} />;
}

const tabs = [
  { id: "library", label: "我的曲谱" },
  { id: "official", label: "官方曲谱" },
  { id: "practice", label: "练习记录" },
  { id: "ai", label: "黑白键AI" },
  { id: "account", label: "账号" },
] as const;

function TabIcon({ kind, isDark }: { kind: string; isDark: boolean }) {
  if (kind === "library") {
    const icon = isDark ? myScoresDarkIcon : myScoresLightIcon;
    return <img src={icon} alt="" className="h-[27px] w-[27px] object-contain" />;
  }

  if (kind === "ai") {
    return <img src={aiIcon} alt="" className="h-[27px] w-[27px] object-contain" />;
  }

  if (kind === "practice") {
    return <img src={isDark ? practiceHistoryDarkIcon : practiceHistoryLightIcon} alt="" className="h-[27px] w-[27px] object-contain" />;
  }

  if (kind === "official") {
    return <img src={isDark ? officialScoresDarkIcon : officialScoresLightIcon} alt="" className="h-[27px] w-[27px] object-contain" />;
  }

  if (kind === "account") {
    return <img src={isDark ? accountTabDarkIcon : accountTabLightIcon} alt="" className="h-[27px] w-[27px] object-contain" />;
  }

  return null;
}

function currentPracticeDay() {
  const date = new Date();
  return Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()) / 86400000;
}

function useSavedOptions() {
  const { send } = useYinban();
  const [options, setOptions] = useState<Record<string, boolean>>(() => {
    try {
      const saved = JSON.parse(localStorage.getItem("music-settings") || "{}");
      return saved && typeof saved === "object" && !Array.isArray(saved) ? saved : {};
    } catch { return {}; }
  });
  useEffect(() => {
    try { localStorage.setItem("music-settings", JSON.stringify(options)); } catch {}
    send("preferences", { soundEnabled: options["音效"] ?? true, hapticEnabled: options["触觉反馈"] ?? true, encouragementEnabled: options["鼓励信息"] ?? true });
  }, [options]);
  return { options, toggle: (key: string, fallback: boolean) => setOptions((previous) => ({ ...previous, [key]: !(previous[key] ?? fallback) })) };
}

function SettingSwitch({ label, description, checked, onChange }: { label: string; description?: string; checked: boolean; onChange: () => void }) {
  return (
    <div className="flex min-h-[60px] items-center justify-between gap-4 py-3">
      <div><p className="text-[20px] font-bold">{label}</p>{description && <p className="mt-1 text-[15px] leading-6 text-[#999]">{description}</p>}</div>
      <button type="button" role="switch" aria-label={label} aria-checked={checked} onClick={onChange} className="relative flex h-10 w-[62px] shrink-0 cursor-pointer items-center focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current">
        <span className={`absolute inset-x-0 h-6 rounded-full transition-colors ${checked ? "bg-[#67db23]" : "bg-[#e5e5e5]"}`} />
        <span className={`relative h-9 w-8 rounded-[10px] border-2 bg-white transition-transform ${checked ? "translate-x-[30px] border-[#67db23]" : "border-[#e5e5e5]"}`} />
      </button>
    </div>
  );
}

const courseImages: Record<string, string> = {
  "小提琴": violinCourse, "中提琴": violaCourse, "大提琴": celloCourse,
  "低音提琴": doubleBassCourse, "竖琴": harpCourse, "钢琴": pianoCourse,
  "长笛": fluteCourse, "单簧管": clarinetCourse, "巴松管": bassoonCourse,
  "双簧管": oboeCourse, "圆号": frenchHornCourse, "小号": trumpetCourse,
  "长号": tromboneCourse, "大号": tubaCourse, "上低音号": euphoniumCourse,
};

function CoursesPage({ isDark, selectedCourse, onCourseChange, onContinue }: { isDark: boolean; selectedCourse: string | null; onCourseChange: (id: string) => void; onContinue: () => void }) {
  const [collapsedGroups, setCollapsedGroups] = useState<string[]>([]);
  const groups = [
    { title: "弦乐", courses: [{ name: "小提琴", image: violinCourse }, { name: "中提琴", image: violaCourse }, { name: "大提琴", image: celloCourse }, { name: "低音提琴", image: doubleBassCourse }, { name: "竖琴", image: harpCourse }] },
    { title: "打击乐", courses: [{ name: "钢琴", image: pianoCourse }] },
    { title: "木管", courses: [{ name: "长笛", image: fluteCourse }, { name: "单簧管", image: clarinetCourse }, { name: "巴松管", image: bassoonCourse }, { name: "双簧管", image: oboeCourse }] },
    { title: "铜管", courses: [{ name: "圆号", image: frenchHornCourse }, { name: "小号", image: trumpetCourse }, { name: "长号", image: tromboneCourse }, { name: "大号", image: tubaCourse }, { name: "上低音号", image: euphoniumCourse }] },
  ];
  return <div className="flex min-h-0 flex-1 flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pt-7 pb-6 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
      {groups.map((group) => <section key={group.title} className="mb-7">
        <button type="button" aria-expanded={!collapsedGroups.includes(group.title)} onClick={() => setCollapsedGroups((previous) => previous.includes(group.title) ? previous.filter((title) => title !== group.title) : [...previous, group.title])} className="mb-4 flex h-9 w-full cursor-pointer items-center justify-between text-[22px] font-bold focus-visible:outline-2 focus-visible:outline-current">
          <span>{group.title}</span><svg width="23" height="23" viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={collapsedGroups.includes(group.title) ? "rotate-180" : ""}><path d="m5 15 7-7 7 7" /></svg>
        </button>
        {!collapsedGroups.includes(group.title) && <div className="flex flex-col gap-3">
          {group.courses.length === 0 && <p className="py-3 text-[15px] text-[#aaa]">暂无课程</p>}
          {group.courses.map((course) => {
            const id = `${group.title}-${course.name}`;
            return <button key={id} type="button" aria-pressed={selectedCourse === id} onClick={() => onCourseChange(id)} className={`flex h-[62px] w-full cursor-pointer items-center gap-4 rounded-[14px] border-2 border-b-[5px] px-4 text-left text-[22px] font-bold focus-visible:outline-2 focus-visible:outline-current ${pressFeedback} ${selectedCourse === id ? isDark ? "border-[#67db23] bg-[#67db23]/10" : "border-[#67db23] bg-[#effbe7]" : isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
              <span className="flex h-11 w-11 shrink-0 items-center justify-center">
                <img src={course.image} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
              </span><span>{course.name}</span>
            </button>;
          })}
        </div>}
      </section>)}
    </div>
    <footer className={`shrink-0 border-t-2 px-4 pt-5 pb-[max(28px,env(safe-area-inset-bottom))] ${isDark ? "border-white/10 bg-[#191919]" : "border-[#e5e5e5] bg-white"}`}>
      <button type="button" disabled={!selectedCourse} onClick={onContinue} className={`h-12 w-full cursor-pointer rounded-[14px] border-b-[5px] border-[#48aa16] bg-[#67db23] text-[17px] font-bold text-white focus-visible:outline-2 focus-visible:outline-current disabled:cursor-default disabled:border-transparent disabled:bg-[#e5e5e5] disabled:text-[#aaa] ${pressFeedback}`}>继续</button>
    </footer>
  </div>;
}

function SettingsContent({ title, isDark, toggleTheme, name, onNameChange }: { title: string; isDark: boolean; toggleTheme: () => void; name: string; onNameChange: (name: string) => void }) {
  const { options, toggle } = useSavedOptions();
  const { send, native } = useYinban();
  const [message, setMessage] = useState("");
  const [notificationGroup, setNotificationGroup] = useState<string | null>(null);
  const [classCode, setClassCode] = useState("");
  const [createClassOpen, setCreateClassOpen] = useState(false);
  const [classroomName, setClassroomName] = useState("");
  const [classroomMessage, setClassroomMessage] = useState("");
  const [avatar, setAvatar] = useState<string | null>(() => { try { return localStorage.getItem("music-profile-avatar"); } catch { return null; } });
  const avatarInput = useRef<HTMLInputElement>(null);
  const codeInputs = useRef<(HTMLInputElement | null)[]>([]);
  const [profile, setProfile] = useState(() => { try { return JSON.parse(localStorage.getItem("music-local-profile") || "null") || { username: "", email: "", phone: "" }; } catch { return { username: "", email: "", phone: "" }; } });
  useEffect(() => { try { localStorage.setItem("music-local-profile", JSON.stringify(profile)); } catch {} }, [profile]);
  const outline = isDark ? "border-white/15" : "border-[#e5e5e5]";
  const field = `mt-2 h-12 w-full rounded-[13px] border-2 px-4 text-[18px] font-normal outline-none focus:border-[#67db23] ${isDark ? "border-white/15 bg-white/5" : "border-[#e5e5e5] bg-[#f7f7f7]"}`;
  const action = `h-12 w-full cursor-pointer rounded-[14px] border-2 border-b-[5px] text-[16px] font-bold text-[#67db23] focus-visible:outline-2 focus-visible:outline-current ${outline} ${pressFeedback}`;
  const toggleRow = (label: string, fallback = true, description?: string) => <SettingSwitch key={label} label={label} description={description} checked={options[label] ?? fallback} onChange={() => toggle(label, fallback)} />;
  const notice = <p role="status" className="mt-4 text-[13px] leading-6 text-[#999]">{message}</p>;

  if (title === "偏好设置") return (
    <div className="px-4 py-7">
      <h2 className="mb-4 text-[15px] font-medium text-[#aaa]">学习体验</h2>
      {["音效", "触觉反馈", "鼓励信息"].map((label) => toggleRow(label))}
      <div className={`my-6 border-t-2 ${outline}`} />
      <h2 className="mb-4 text-[15px] font-medium text-[#aaa]">专注模式设置</h2>
      {toggleRow("屏蔽其他应用", false)}
      <button type="button" onClick={() => setMessage("当前为网页预览，无法屏蔽其他手机应用。")} className="flex h-14 w-full cursor-pointer items-center justify-between text-[18px] font-bold text-[#aaa]"><span>屏蔽设置</span><span className="text-[15px]">设置</span></button>
      <p className="text-[12px] leading-6 text-[#aaa]">本机偏好已保存。演奏模式、输入、节拍器与容差请在练习页面的设置中调整。</p>
      <div className={`my-6 border-t-2 ${outline}`} />
      <h2 className="mb-2 text-[15px] font-medium text-[#aaa]">外观</h2>
      <SettingSwitch label="深色模式" checked={isDark} onChange={toggleTheme} />
      {notice}
    </div>
  );

  if (title === "个人档案") return (
    <div className="px-4 py-5">
      <div className="mb-7 flex flex-col items-center gap-3">
        <div className="flex h-24 w-24 items-center justify-center overflow-hidden rounded-full border-2 border-[#67db23] bg-[#f3f3f3] p-2"><img src={avatar || accountLightIcon} alt="账号头像" className="h-full w-full object-contain" /></div>
        <button type="button" onClick={() => avatarInput.current?.click()} className="cursor-pointer text-[17px] font-bold text-[#67db23]">更改头像</button>
        <input ref={avatarInput} type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          if (file.size > 2 * 1024 * 1024 || !["image/png", "image/jpeg", "image/webp"].includes(file.type)) { setMessage("请选择不超过 2MB 的 PNG、JPG 或 WebP 图片。"); return; }
          const reader = new FileReader();
          reader.onload = () => { try { const image = String(reader.result); localStorage.setItem("music-profile-avatar", image); setAvatar(image); window.dispatchEvent(new Event("yinban-profile-update")); setMessage("头像已保存在本机。"); } catch { setMessage("头像保存失败，本机存储空间不足。"); } };
          reader.readAsDataURL(file);
        }} />
      </div>
      <label className="mb-4 block text-[19px] font-bold">姓名<input value={name} onChange={(event) => onNameChange(event.target.value)} maxLength={30} placeholder="请输入姓名" autoComplete="name" className={field} /></label>
      <label className="mb-4 block text-[19px] font-bold">用户名<input value={profile.username} onChange={(event) => setProfile({ ...profile, username: event.target.value })} autoComplete="username" placeholder="请输入用户名" className={field} /></label>
      <label className="mb-4 block text-[19px] font-bold">密码<input type="password" disabled placeholder="接入账号服务后可修改" className={`${field} text-[14px] disabled:opacity-60`} /></label>
      <label className="mb-4 block text-[19px] font-bold">邮箱<input type="email" value={profile.email} onChange={(event) => setProfile({ ...profile, email: event.target.value })} autoComplete="email" placeholder="请输入邮箱" className={field} /></label>
      <label className="mb-4 block text-[19px] font-bold">电话号码<input type="tel" value={profile.phone} onChange={(event) => setProfile({ ...profile, phone: event.target.value })} autoComplete="tel" placeholder="请输入电话号码" className={field} /></label>
      <p className="mb-5 text-[12px] text-[#999]">个人档案只保存在本机；尚未开通远程账号与跨设备同步。</p>
      <button type="button" className={action} onClick={() => send("exportData")}>导出数据</button>
      <button type="button" disabled className={`${action} mt-3 text-[#aaa]`}>远程账号尚未开通</button>
      {notice}
    </div>
  );

  if (title === "通知") {
    const groups = [
      { name: "提醒", description: "每日练习与连胜提醒", items: ["每日练琴提醒", "连胜提醒", "练习目标提醒", "周报提醒", "未打卡提醒"] },
      { name: "好友", description: "新关注及好友成就更新", items: ["新关注", "好友成就"] },
      { name: "排行榜", description: "所在排行榜的排位更新", items: ["排位更新"] },
      { name: "公告", description: "新功能、优惠及活动", items: ["新功能", "优惠", "活动"] },
      { name: "好友提醒", description: "来自好友的提醒", items: ["好友练习提醒", "好友邀请", "好友消息"] },
    ];
    return <div className="px-4 py-4">{groups.map((group) => (
      <section key={group.name} className="py-3">
        <button type="button" aria-expanded={notificationGroup === group.name} onClick={() => setNotificationGroup((previous) => previous === group.name ? null : group.name)} className="flex w-full cursor-pointer items-center justify-between gap-4 text-left">
          <div><h2 className="text-[20px] font-bold">{group.name}</h2><p className="mt-1 text-[16px] text-[#999]">{group.description}</p><p className="mt-1 text-[15px] font-bold text-[#67db23]">已关闭 {group.items.filter((item) => !(options[`通知-${item}`] ?? false)).length} 条通知</p></div>
          <svg width="20" height="24" viewBox="0 0 24 24" fill="none" stroke="#aaa" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={notificationGroup === group.name ? "rotate-90" : ""} aria-hidden="true"><path d="m9 4 8 8-8 8" /></svg>
        </button>
        {notificationGroup === group.name && <div className={`mt-3 rounded-xl border px-3 ${outline}`}>{group.items.map((item) => <SettingSwitch key={item} label={item} checked={options[`通知-${item}`] ?? false} onChange={() => toggle(`通知-${item}`, false)} />)}</div>}
      </section>
    ))}<p className="mt-5 text-[12px] leading-6 text-[#aaa]">此处保存通知偏好，实际推送尚未接入。</p></div>;
  }

  if (title === "隐私设置") return <div className="px-4 py-5"><h2 className="text-xl font-bold">你的文件与声音</h2><p className="mt-4 text-sm leading-7 text-[#999]">图片和 PDF 识谱时发送至你配置的云端 OMR 服务器。服务器运营者、保存期限和数据使用方式由该服务决定。麦克风声音在设备中实时识别，不上传音频；练习记录保存在本机。</p><p className="mt-4 text-sm leading-7 text-[#999]">当前版本没有广告跟踪或训练数据收集服务。</p><button onClick={() => send("privacy")} className={`${action} mt-5`}>查看隐私政策</button></div>;

  if (title === "黑白键课堂") return (
    <div>
      <div className="flex h-48 items-center justify-center overflow-hidden bg-[#67db23]"><img src={aiIcon} alt="黑白键练琴小猫" className="h-44 w-44 object-contain" /></div>
      <div className="px-4 py-7">
        <section aria-labelledby="create-class-title" className={`mb-7 border-b-2 pb-7 ${outline}`}>
          <h2 id="create-class-title" className="text-[24px] font-bold">创建课堂</h2>
          <p className="mt-4 text-[15px] leading-7 text-[#999]">课堂服务尚未开通。此页面保留课堂设计；当前不能创建课堂、邀请学生或共享练习记录。</p>
          {!createClassOpen ? (
            <button type="button" disabled onClick={() => setCreateClassOpen(true)} className={`${action} mt-5 flex items-center justify-center text-center`}>
              创建课堂
            </button>
          ) : (
            <form className="mt-5" onSubmit={(event) => { event.preventDefault(); setClassroomMessage(`已填写「${classroomName.trim()}」。创建课堂服务尚未接入，暂未创建真实课堂。`); }}>
              <label className="block text-[17px] font-bold">课堂名称<input autoFocus required maxLength={40} value={classroomName} onChange={(event) => { setClassroomName(event.target.value); setClassroomMessage(""); }} placeholder="例如：周六钢琴基础班" className={field} /></label>
              <div className="mt-4 flex gap-3">
                <button type="button" onClick={() => { setCreateClassOpen(false); setClassroomMessage(""); }} className={`${action} flex-1 text-[#999]`}>取消</button>
                <button type="submit" disabled={!classroomName.trim()} className="h-12 flex-1 cursor-pointer rounded-[14px] bg-[#67db23] text-[16px] font-bold text-white disabled:cursor-default disabled:bg-[#e5e5e5] disabled:text-[#aaa]">确认创建</button>
              </div>
              <p role="status" className="mt-3 text-[13px] leading-6 text-[#999]">{classroomMessage}</p>
            </form>
          )}
        </section>
        <h2 className="text-[24px] font-bold">加入课堂</h2><p className="mt-4 text-[15px] leading-7 text-[#999]">请输入老师发给你的课堂代码。加入课堂后，老师可以了解你的练琴进度、布置练习并帮助管理学习计划。</p>
        <div className="mt-5 grid grid-cols-6 gap-2" role="group" aria-label="六位课堂代码">
          {Array.from({ length: 6 }, (_, index) => <input key={index} ref={(element) => { codeInputs.current[index] = element; }} aria-label={`课堂代码第${index + 1}位`} value={classCode[index] || ""} maxLength={1} autoCapitalize="characters" autoComplete="off" onChange={(event) => {
            const character = event.target.value.replace(/[^a-zA-Z0-9]/g, "").toUpperCase().slice(-1);
            setClassCode((previous) => previous.padEnd(6, " ").slice(0, index) + (character || " ") + previous.padEnd(6, " ").slice(index + 1));
            setMessage("");
            if (character && index < 5) codeInputs.current[index + 1]?.focus();
          }} onKeyDown={(event) => {
            if (event.key === "Backspace" && !classCode[index]?.trim() && index > 0) codeInputs.current[index - 1]?.focus();
          }} onPaste={(event) => {
            event.preventDefault();
            const pasted = event.clipboardData.getData("text").replace(/[^a-zA-Z0-9]/g, "").toUpperCase().slice(0, 6);
            setClassCode(pasted); setMessage(""); codeInputs.current[Math.min(pasted.length, 5)]?.focus();
          }} className={`${field} h-14 px-0 text-center text-[22px]`} />)}
        </div>
        <button type="button" disabled onClick={() => setMessage("课堂服务尚未接入，暂时无法验证代码。")} className="mt-5 h-12 w-full cursor-pointer rounded-[14px] bg-[#67db23] text-[17px] font-bold text-white disabled:cursor-default disabled:bg-[#e5e5e5] disabled:text-[#aaa]">提交</button>{notice}
      </div>
    </div>
  );

  if (title === "挑选套餐") return (
    <div className="px-5 py-4"><h2 className="mb-4 text-[15px] font-medium text-[#aaa]">可选套餐</h2>
      {[
        { name: "专业个人套餐", subtitle: "专心练琴无打扰", perks: ["无限练习", "免广告"], badge: "∞" },
        { name: "校园套餐", subtitle: "共享 Super 福利", perks: ["所有福利无限", "按席位阶梯收费"], badge: "校" },
        { name: "Lite（含广告）", subtitle: "更多练习，更好进步", perks: ["每日双倍练习额度", "更快恢复练习额度"], badge: "2×" },
      ].map((plan, index) => <section key={plan.name} className={`mb-5 overflow-hidden rounded-[18px] border-2 ${outline}`}>
        {index === 0 && <div className="bg-gradient-to-r from-[#ac3ce9] via-[#67db23] to-[#23ba9c] px-4 py-2 text-[15px] font-bold text-white">推荐</div>}
        <div className="relative p-4"><div className="pr-14"><h3 className="text-[21px] font-bold">{plan.name}</h3><p className="mt-1 text-[15px] text-[#999]">{plan.subtitle}</p></div>
          <svg viewBox="0 0 64 64" aria-hidden="true" className="absolute right-3 top-4 h-14 w-14">
            <defs><linearGradient id={`plan-badge-gradient-${index}`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="#67db23" /><stop offset="1" stopColor="#7958ee" /></linearGradient></defs>
            <g transform="rotate(12 32 32)">
              <rect x="6" y="6" width="52" height="52" rx="18" fill={index === 2 ? "#ea58b4" : `url(#plan-badge-gradient-${index})`} />
              <text x="32" y={index === 1 ? 30 : 29} textAnchor="middle" dominantBaseline="central" fill="white" className={index === 0 ? "text-[32px] font-bold" : "text-[26px] font-bold"}>{plan.badge}</text>
            </g>
          </svg>
          <ul className="my-5 space-y-3">{plan.perks.map((perk) => <li key={perk} className="flex items-start gap-3 text-[16px]"><span className="font-bold text-[#67db23]">✓</span>{perk}</li>)}</ul>
          <button type="button" disabled className={`${action} text-[#67db23]`}>套餐尚未开通</button>
        </div>
      </section>)}<p className="text-[12px] text-[#aaa]">当前功能免费使用；尚未提供付费套餐，未限制练习次数。</p>{notice}
    </div>
  );

  if (title === "反馈" || title === "客服中心") return <div className="px-5 py-7"><h2 className="text-xl font-bold">我们在听</h2><p className="my-4 text-sm leading-7 text-[#999]">请描述问题出现在哪个页面、操作步骤和设备型号。发送前可以附上截图；不要发送密码或密钥。</p><button onClick={() => send("feedback")} className={action}>通过邮件反馈</button><p className="mt-4 text-sm text-[#999]">Lucas.z0623@outlook.com</p></div>;
  if (title === "隐私政策" || title === "条款") return <div className="px-5 py-7"><h2 className="text-xl font-bold">本机练习与云端识谱</h2><p className="my-4 text-sm leading-7 text-[#999]">曲谱和练习记录保存在本机。图片和 PDF 识谱会上传至所配置的云端服务，使用前请了解该服务的数据政策。声音识别在设备上处理。识谱与演奏反馈可能存在误差，请结合原谱核对。</p><button onClick={() => native ? send("privacy") : setMessage("此交互预览不会上传你的曲谱、声音或个人档案。")} className={action}>查看数据处理说明</button>{notice}</div>;
  if (title === "致谢") return <div className="px-5 py-7"><h2 className="text-xl font-bold">致谢</h2><p className="mt-4 text-sm leading-7 text-[#999]">音伴使用 OpenSheetMusicDisplay、Pitchy 与其他开源组件。Orpheus AI 云端识谱使用 Audiveris 技术；原始版权及开源许可保留。界面字体为 Noto Sans SC，遵循 SIL Open Font License。</p><button onClick={() => send("privacy")} className={`${action} mt-5`}>查看完整说明</button></div>;
  if (title === "云端识谱") return <div className="px-5 py-7"><p className="mb-5 text-sm leading-7 text-[#999]">使用 Orpheus AI 云端 OMR 服务将 PDF 和图片转换为可练习的 MusicXML。服务器地址和访问凭据保存在设备中，凭据不会发送给此界面。</p><button className={action} onClick={() => send("serverSettings")}>打开服务器设置</button></div>;
  return <div className="px-5 py-8"><h2 className="text-xl font-bold">{title}</h2><p className="mt-4 text-sm leading-7 text-[#999]">{["关注", "关注者", "添加好友", "我的二维码"].includes(title) ? "好友与账号服务尚未开通，当前使用本机档案。" : title === "恢复订购" ? "当前没有付费订购，无需恢复。" : "当前使用本机档案，没有远程登录会话。"}</p></div>;
}

function AccountSymbol({ kind, className = "h-6 w-6" }: { kind: string; className?: string }) {
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={className}>
    {kind === "person" && <><circle cx="9" cy="7" r="4" fill="currentColor" stroke="none" /><path d="M2 21v-2a7 7 0 0 1 14 0v2Z" fill="currentColor" stroke="none" /><path d="M20 8v8M16 12h8" /></>}
    {kind === "qr" && <>
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="15" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="15" width="7" height="7" rx="1.5" />
      <g fill="currentColor" stroke="none">
        <rect x="4.5" y="4.5" width="2" height="2" rx="0.4" />
        <rect x="17.5" y="4.5" width="2" height="2" rx="0.4" />
        <rect x="4.5" y="17.5" width="2" height="2" rx="0.4" />
        <rect x="15" y="15" width="3" height="3" rx="0.5" />
        <rect x="20" y="15" width="2" height="2" rx="0.4" />
        <rect x="15" y="20" width="2" height="2" rx="0.4" />
        <rect x="19" y="19" width="3" height="3" rx="0.5" />
      </g>
    </>}
    {kind === "trophy" && <><path d="M7 3h10v7a5 5 0 0 1-10 0ZM7 5H3v3a4 4 0 0 0 4 4M17 5h4v3a4 4 0 0 1-4 4M12 15v6M8 21h8" /></>}
    {kind === "bolt" && <path d="m14 2-10 12h7l-1 8 10-12h-7Z" fill="currentColor" stroke="none" />}
    {kind === "medal" && <><circle cx="12" cy="9" r="6" fill="currentColor" stroke="none" /><path d="m8 14-1 8 5-3 5 3-1-8" fill="currentColor" stroke="none" /></>}
    {kind === "lock" && <><rect x="5" y="10" width="14" height="11" rx="3" fill="currentColor" stroke="none" /><path d="M8 10V7a4 4 0 0 1 8 0v3" strokeWidth="3" /></>}
    {kind === "music" && <><path d="M10 18V5l10-2v13M10 9l10-2" /><ellipse cx="7" cy="18.5" rx="3" ry="2.5" fill="currentColor" /><ellipse cx="17" cy="16.5" rx="3" ry="2.5" fill="currentColor" /></>}
  </svg>;
}

function CostumeCat({ kind }: { kind: string }) {
  const color = ({ piano: "#e8e8ed", dinosaur: "#61bf37", lava: "#8890ee", robot: "#9db4bf", duck: "#ffd34f", royal: "#b992e9" } as Record<string, string>)[kind] || "#e9e9e9";
  return <svg viewBox="0 0 128 150" aria-hidden="true" className="h-full w-full">
    {kind !== "plain" && <>
      <rect x="14" y="16" width="100" height="128" rx={kind === "piano" ? 12 : 40} fill={color} />
      {kind === "piano" && <><path d="M47 18v125M80 18v125" stroke="white" strokeWidth="3" /><path d="M46 18v35M80 18v35" stroke="#333" strokeWidth="13" /></>}
      {kind === "dinosaur" && <><circle cx="33" cy="25" r="14" fill="#79d74b" /><circle cx="95" cy="25" r="14" fill="#79d74b" /><circle cx="34" cy="24" r="8" fill="white" /><circle cx="94" cy="24" r="8" fill="white" /><circle cx="35" cy="24" r="4" fill="#333" /><circle cx="93" cy="24" r="4" fill="#333" /></>}
      {kind === "lava" && <><ellipse cx="64" cy="10" rx="33" ry="10" fill="#35353d" /><ellipse cx="38" cy="116" rx="13" ry="17" fill="#a2f06e" /><ellipse cx="88" cy="125" rx="12" ry="15" fill="#a2f06e" /></>}
      {kind === "robot" && <><path d="M64 16V4" stroke="#648391" strokeWidth="5" /><circle cx="64" cy="5" r="5" fill="#8add70" /><rect x="4" y="57" width="14" height="33" rx="5" fill="#69828f" /><rect x="110" y="57" width="14" height="33" rx="5" fill="#69828f" /></>}
      {kind === "duck" && <><ellipse cx="64" cy="26" rx="16" ry="7" fill="#ed981a" /><circle cx="43" cy="15" r="4" fill="#333" /><circle cx="85" cy="15" r="4" fill="#333" /></>}
    </>}
    <image href={accountLightIcon} x="22" y={kind === "plain" ? 17 : 35} width="84" height="100" />
  </svg>;
}

function OutfitProgress({ isDark, selectedId, onBack, onPractice, onPreview }: { isDark: boolean; selectedId: string; onBack: () => void; onPractice: () => void; onPreview: (id: string) => void }) {
  const { state } = useYinban();
  const stats = summarizeHistory(state.history);
  const [clock, setClock] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 30000);
    return () => window.clearInterval(timer);
  }, []);
  const midnight = new Date(clock);
  midnight.setHours(24, 0, 0, 0);
  const remainingMinutes = Math.ceil((midnight.getTime() - clock) / 60000);
  const selected = wardrobeOutfits.find((outfit) => outfit.id === selectedId) || wardrobeOutfits[1];
  const featured = wardrobeOutfits.filter((outfit) => outfit.practiceExclusive && outfit.id !== selectedId).slice(0, 4);
  const heroImages = [featured[0], featured[1], selected, featured[2], featured[3]];
  const outline = isDark ? "border-white/15" : "border-[#e5e5e5]";
  return <div className="mx-auto min-h-full w-full max-w-none sm:max-w-[680px] pb-[max(28px,env(safe-area-inset-bottom))]">
    <header className="sticky top-0 z-20 bg-[#67db23] pt-[var(--yinban-top-inset)] text-white">
      <div className="relative flex h-14 items-center justify-center">
        <button type="button" aria-label="返回装扮预览" onClick={onBack} className="absolute left-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full active:bg-white/15 focus-visible:outline-2 focus-visible:outline-current"><svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m11 4-8 8 8 8M3 12h18" /></svg></button>
        <h1 id="outfit-progress-title" className="text-[20px] font-bold">音乐家的装扮寻宝</h1>
      </div>
    </header>
    <section className="overflow-hidden bg-[#67db23] px-4 pt-2">
      <p className="text-center text-[14px] font-bold text-white/90">练琴收集，解锁你的音乐家造型</p>
      <div className="mt-4 flex h-[174px] items-end justify-center -space-x-4">
        {heroImages.map((outfit, index) => <img key={`${outfit.id}-${index}`} src={outfit.image} alt={index === 2 ? outfit.label : ""} className={`shrink-0 object-contain object-bottom ${index === 2 ? "relative z-10 h-[174px] w-[116px]" : index === 1 || index === 3 ? "relative z-[5] h-[142px] w-[100px]" : "h-[116px] w-[80px]"}`} />)}
      </div>
    </section>
    <div className="px-5 pt-5">
      <section aria-labelledby="daily-rewards-title">
        <div className="mb-1 flex items-center justify-between gap-2 text-[14px] font-bold text-[#aaa]"><span>每日奖励</span><span className="flex items-center gap-1.5 text-[12px]"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l-3 2" /></svg>今日剩余 {Math.floor(remainingMinutes / 60)} 小时 {remainingMinutes % 60} 分</span></div>
        <h2 id="daily-rewards-title" className="text-[20px] font-bold leading-8">完成练习，赚取拼图碎片</h2>
        <div className="mt-3 flex gap-2.5 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
          {[1, 2, 4, 6].map((target) => <div key={target} className="w-[31%] min-w-[100px] shrink-0">
            <div className={`overflow-hidden rounded-[17px] border-2 ${outline}`}>
              <div className="flex h-[96px] items-center justify-center"><div className="flex h-14 w-12 items-center justify-center rounded-[9px] border-2 border-b-[5px] border-[#48aa16] bg-[#67db23] text-white"><AccountSymbol kind="music" className="h-7 w-7" /></div></div>
              <div className={`px-2 py-2.5 ${isDark ? "bg-white/5" : "bg-[#f7f7f7]"}`}><div role="progressbar" aria-label={`完成${target}首练习奖励`} aria-valuemin={0} aria-valuemax={target} aria-valuenow={Math.min(stats.todayCompleted, target)} className={`h-3 rounded-full ${isDark ? "bg-white/10" : "bg-[#e5e5e5]"}`}><div className="h-3 rounded-full bg-[#67db23]" style={{ width: `${Math.min(100, stats.todayCompleted / target * 100)}%` }} /></div></div>
            </div><p className="mt-2 text-center text-[15px] font-bold text-[#aaa]">{target} 首练习</p>
          </div>)}
        </div>
        <button type="button" onClick={onPractice} className={`mt-5 h-12 w-full cursor-pointer rounded-[14px] border-b-[5px] border-[#48aa16] bg-[#67db23] text-[18px] font-bold text-white focus-visible:outline-2 focus-visible:outline-current ${pressFeedback}`}>去练一首</button>
      </section>
      <section aria-labelledby="outfit-puzzles-title" className={`mt-6 border-t-2 pt-5 ${outline}`}>
        <p className="text-[14px] font-bold text-[#aaa]">你的拼图</p>
        <h2 id="outfit-puzzles-title" className="mt-1 text-[20px] font-bold leading-8">收集拼图碎片，解锁各式装扮</h2>
        <p className="mb-4 text-[12px] leading-6 text-[#aaa]">每完成 3 次练习按顺序解锁一套装扮；猫咪造型也遵循此规则。删除记录后会重新计算进度。</p>
        <div className="grid grid-cols-3 gap-x-3 gap-y-6">
          {wardrobeOutfits.filter((outfit) => outfit.id !== "plain").map((outfit, outfitIndex) => <div key={outfit.id}>
            <button type="button" aria-label={`预览${outfit.label}，尚未解锁`} onClick={() => onPreview(outfit.id)} className={`relative flex aspect-[0.8] w-full cursor-pointer items-center justify-center rounded-[18px] border-2 border-b-[5px] px-1 pt-2 focus-visible:outline-2 focus-visible:outline-current ${pressFeedback} ${outfit.id === selectedId ? "border-[#a0eb76] bg-[#effbe7]" : outfit.practiceExclusive ? "border-[#e0d5f0]" : outline}`}>
              {outfit.practiceExclusive && <span className="absolute -top-3 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#b395d5] px-1.5 py-0.5 text-[11px] font-bold text-white">练琴专属</span>}
              <img src={outfit.image} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" />
            </button>
            <div role="progressbar" aria-label={`${outfit.label}解锁进度`} aria-valuemin={0} aria-valuemax={(outfitIndex + 1) * 3} aria-valuenow={Math.min(stats.completed, (outfitIndex + 1) * 3)} className={`mt-2 h-3 rounded-full ${isDark ? "bg-white/10" : "bg-[#e5e5e5]"}`}><div className="h-3 rounded-full bg-[#67db23]" style={{ width: `${Math.min(100, stats.completed / ((outfitIndex + 1) * 3) * 100)}%` }} /></div>
            <p className="mt-2 text-center text-[13px] font-bold leading-5 text-[#aaa]">{outfit.label}</p>
          </div>)}
        </div>
      </section>
    </div>
  </div>;
}

function ScorePathSymbol({ kind }: { kind: string }) {
  return <svg viewBox="0 0 48 48" fill="none" className="h-9 w-9" aria-hidden="true">
    {kind === "wave" && <g stroke="white" strokeWidth="5" strokeLinecap="round"><path d="M8 21v6M16 15v18M24 8v32M32 15v18M40 21v6" /></g>}
    {kind === "star" && <path d="m24 4 6 13 14 2-10 10 2 14-12-7-12 7 2-14L4 19l14-2Z" fill="white" stroke="white" strokeWidth="2" strokeLinejoin="round" />}
    {kind === "music" && <g fill="white"><path d="M22 9h16v7H28v20h-6Z" /><ellipse cx="18" cy="36" rx="10" ry="7" /></g>}
    {kind === "notes" && <g fill="white"><path d="M15 11 39 6v29h-6V14l-12 3v23h-6Z" /><ellipse cx="11" cy="39" rx="8" ry="6" /><ellipse cx="29" cy="34" rx="8" ry="6" /></g>}
    {kind === "tempo" && <g stroke="white" strokeWidth="4" strokeLinecap="round"><path d="M7 36a19 19 0 1 1 34 0M24 8v5M9 18l4 3M39 18l-4 3M10 35h4M38 35h-4M24 30l9-10" /><circle cx="24" cy="30" r="3" fill="white" /></g>}
    {kind === "triangle" && <path d="m22 8-16 29h34L25 11M29 28l13-10" stroke="white" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />}
  </svg>;
}

const firstStagePieces = [
  { title: "入门练习曲第 1 首", composer: "车尔尼", workNumber: "Op.599 No.1" },
  { title: "中板小品第 1 首", composer: "古尔利特", workNumber: "Op.117 No.1" },
  { title: "万事开头难", composer: "蒂尔克", workNumber: "原集 I/1" },
  { title: "入门练习曲第 2 首", composer: "车尔尼", workNumber: "Op.599 No.2" },
  { title: "中板小品第 2 首", composer: "古尔利特", workNumber: "Op.117 No.2" },
  { title: "懒人", composer: "蒂尔克", workNumber: "原集 I/2" },
  { title: "小步舞曲第 1 首", composer: "赖纳格尔", workNumber: "Op.1 No.1" },
  { title: "入门练习曲第 3 首", composer: "车尔尼", workNumber: "Op.599 No.3" },
  { title: "活跃地：小品第 3 首", composer: "古尔利特", workNumber: "Op.117 No.3" },
  { title: "活泼的男孩", composer: "蒂尔克", workNumber: "原集 I/3" },
  { title: "小步舞曲第 2 首", composer: "赖纳格尔", workNumber: "Op.1 No.2" },
  { title: "入门练习曲第 4 首", composer: "车尔尼", workNumber: "Op.599 No.4" },
  { title: "无忧无虑的汉斯", composer: "蒂尔克", workNumber: "原集 I/4" },
  { title: "快板小品第 3 首", composer: "赖纳格尔", workNumber: "Op.1 No.3" },
  { title: "优雅的小快板", composer: "古尔利特", workNumber: "Op.117 No.6" },
  { title: "摇篮曲", composer: "蒂尔克", workNumber: "原集 I/5" },
  { title: "快板小品第 4 首", composer: "赖纳格尔", workNumber: "Op.1 No.4" },
  { title: "活板小品第 8 首", composer: "古尔利特", workNumber: "Op.117 No.8" },
  { title: "音阶", composer: "蒂尔克", workNumber: "原集 I/6" },
  { title: "小快板小品第 5 首", composer: "赖纳格尔", workNumber: "Op.1 No.5" },
  { title: "晨间问候", composer: "古尔利特", workNumber: "Op.117 No.13" },
  { title: "哀叹", composer: "古尔利特", workNumber: "Op.117 No.16" },
  { title: "简易小品第 6 首", composer: "赖纳格尔", workNumber: "Op.1 No.6" },
  { title: "摇篮曲", composer: "古尔利特", workNumber: "Op.117 No.17" },
  { title: "晚歌", composer: "古尔利特", workNumber: "Op.117 No.20" },
  { title: "A 小调小步舞曲", composer: "珀塞尔", workNumber: "Z.649" },
  { title: "C 大调小步舞曲", composer: "莫扎特", workNumber: "K.1f" },
  { title: "G 大调小步舞曲", composer: "莫扎特", workNumber: "K.1 / K.1e" },
  { title: "小曲", composer: "舒曼", workNumber: "Op.68 No.5" },
  { title: "旋律", composer: "舒曼", workNumber: "Op.68 No.1" },
];

const stagePieces = [
  firstStagePieces,
  [
    { title: "上学去", composer: "古尔利特", workNumber: "Op.117 No.14" },
    { title: "好孩子", composer: "古尔利特", workNumber: "Op.117 No.19" },
    { title: "行板小品第 15 首", composer: "赖纳格尔", workNumber: "Op.1 No.15" },
    { title: "进行曲", composer: "古尔利特", workNumber: "Op.140 No.1" },
    { title: "晨歌", composer: "古尔利特", workNumber: "Op.140 No.2" },
    { title: "芭蕾舞", composer: "蒂尔克", workNumber: "原集 I/19" },
    { title: "哼唱的小曲", composer: "舒曼", workNumber: "Op.68 No.3" },
    { title: "F 大调小步舞曲", composer: "莫扎特", workNumber: "K.2" },
    { title: "D 大调进行曲", composer: "C.P.E.巴赫", workNumber: "BWV Anh.122 / H.1 No.1" },
    { title: "G 大调小步舞曲", composer: "佩措尔德", workNumber: "BWV Anh.114" },
    { title: "在花园里", composer: "古尔利特", workNumber: "Op.140 No.4" },
    { title: "轮唱", composer: "古尔利特", workNumber: "Op.117 No.22" },
    { title: "坦诚", composer: "布格缪勒", workNumber: "Op.100 No.1" },
    { title: "士兵进行曲", composer: "舒曼", workNumber: "Op.68 No.2" },
    { title: "圣咏", composer: "舒曼", workNumber: "Op.68 No.4" },
    { title: "降 B 大调快板", composer: "莫扎特", workNumber: "K.3" },
    { title: "牧歌", composer: "布格缪勒", workNumber: "Op.100 No.3" },
    { title: "G 大调进行曲", composer: "C.P.E.巴赫", workNumber: "BWV Anh.124 / H.1 No.3" },
    { title: "G 小调小步舞曲", composer: "佩措尔德", workNumber: "BWV Anh.115" },
    { title: "病中的洋娃娃", composer: "柴可夫斯基", workNumber: "Op.39 No.6" },
    { title: "洋娃娃的葬礼", composer: "柴可夫斯基", workNumber: "Op.39 No.7" },
    { title: "G 小调波兰舞曲", composer: "C.P.E.巴赫", workNumber: "BWV Anh.125 / H.1 No.4" },
    { title: "降 E 大调苏格兰舞曲", composer: "贝多芬", workNumber: "WoO 86" },
    { title: "晴朗的天空", composer: "古尔利特", workNumber: "Op.140 No.3" },
    { title: "F 大调小步舞曲", composer: "莫扎特", workNumber: "K.5" },
    { title: "天真", composer: "布格缪勒", workNumber: "Op.100 No.5" },
    { title: "古老的法国歌曲", composer: "柴可夫斯基", workNumber: "Op.39 No.16" },
    { title: "D 大调缪塞特舞曲", composer: "佚名", workNumber: "BWV Anh.126" },
    { title: "晨祷", composer: "柴可夫斯基", workNumber: "Op.39 No.1" },
    { title: "圣母颂", composer: "布格缪勒", workNumber: "Op.100 No.19" },
  ],
  [
    { title: "娇嫩的花", composer: "布格缪勒", workNumber: "Op.100 No.10" },
    { title: "安慰", composer: "布格缪勒", workNumber: "Op.100 No.13" },
    { title: "阿拉伯风格曲", composer: "布格缪勒", workNumber: "Op.100 No.2" },
    { title: "可怜的孤儿", composer: "舒曼", workNumber: "Op.68 No.6" },
    { title: "温柔的诉说", composer: "布格缪勒", workNumber: "Op.100 No.16" },
    { title: "C 大调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 924" },
    { title: "小聚会", composer: "布格缪勒", workNumber: "Op.100 No.4" },
    { title: "猎人之歌", composer: "舒曼", workNumber: "Op.68 No.7" },
    { title: "施蒂里亚舞曲", composer: "布格缪勒", workNumber: "Op.100 No.14" },
    { title: "C 大调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 933" },
    { title: "清澈的小溪", composer: "布格缪勒", workNumber: "Op.100 No.7" },
    { title: "勇敢的骑士", composer: "舒曼", workNumber: "Op.68 No.8" },
    { title: "告别", composer: "布格缪勒", workNumber: "Op.100 No.12" },
    { title: "快乐的农夫", composer: "舒曼", workNumber: "Op.68 No.10" },
    { title: "C 小调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 934" },
    { title: "天使的和声", composer: "布格缪勒", workNumber: "Op.100 No.21" },
    { title: "船歌", composer: "布格缪勒", workNumber: "Op.100 No.22" },
    { title: "小民歌", composer: "舒曼", workNumber: "Op.68 No.9" },
    { title: "D 小调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 926" },
    { title: "狩猎", composer: "布格缪勒", workNumber: "Op.100 No.9" },
    { title: "玛祖卡", composer: "柴可夫斯基", workNumber: "Op.39 No.10" },
    { title: "小练习曲", composer: "舒曼", workNumber: "Op.68 No.14" },
    { title: "鹡鸰", composer: "布格缪勒", workNumber: "Op.100 No.11" },
    { title: "F 大调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 927" },
    { title: "圆舞曲", composer: "柴可夫斯基", workNumber: "Op.39 No.8" },
    { title: "进步", composer: "布格缪勒", workNumber: "Op.100 No.6" },
    { title: "初次的悲伤", composer: "舒曼", workNumber: "Op.68 No.16" },
    { title: "G 小调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 930" },
    { title: "不安", composer: "布格缪勒", workNumber: "Op.100 No.18" },
    { title: "叙事曲", composer: "布格缪勒", workNumber: "Op.100 No.15" },
  ],
  [
    { title: "D 大调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 936" },
    { title: "民歌", composer: "格里格", workNumber: "Op.12 No.5" },
    { title: "塔兰泰拉", composer: "布格缪勒", workNumber: "Op.100 No.20" },
    { title: "A 大调前奏曲", composer: "肖邦", workNumber: "Op.28 No.7" },
    { title: "圆舞曲", composer: "格里格", workNumber: "Op.12 No.2" },
    { title: "西西里舞曲", composer: "舒曼", workNumber: "Op.68 No.11" },
    { title: "D 小调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 935" },
    { title: "守夜人之歌", composer: "格里格", workNumber: "Op.12 No.3" },
    { title: "C 小调前奏曲", composer: "肖邦", workNumber: "Op.28 No.20" },
    { title: "燕子", composer: "布格缪勒", workNumber: "Op.100 No.24" },
    { title: "C 大调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 772" },
    { title: "致爱丽丝，完整原曲", composer: "贝多芬", workNumber: "WoO 59" },
    { title: "纪念册的一页", composer: "格里格", workNumber: "Op.12 No.7" },
    { title: "骑士风格曲", composer: "布格缪勒", workNumber: "Op.100 No.25" },
    { title: "E 小调前奏曲", composer: "肖邦", workNumber: "Op.28 No.4" },
    { title: "D 小调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 775" },
    { title: "甜梦", composer: "柴可夫斯基", workNumber: "Op.39 No.21" },
    { title: "归来", composer: "布格缪勒", workNumber: "Op.100 No.23" },
    { title: "E 大调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 777" },
    { title: "小咏叹调", composer: "格里格", workNumber: "Op.12 No.1" },
    { title: "B 小调前奏曲", composer: "肖邦", workNumber: "Op.28 No.6" },
    { title: "F 大调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 779" },
    { title: "鲁普雷希特", composer: "舒曼", workNumber: "Op.68 No.12" },
    { title: "旋律", composer: "格里格", workNumber: "Op.38 No.3" },
    { title: "A 小调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 784" },
    { title: "精灵之舞", composer: "格里格", workNumber: "Op.12 No.4" },
    { title: "F 大调小前奏曲", composer: "J.S.巴赫", workNumber: "BWV 928" },
    { title: "悲歌", composer: "格里格", workNumber: "Op.38 No.6" },
    { title: "C 小调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 773" },
    { title: "D 大调二部创意曲", composer: "J.S.巴赫", workNumber: "BWV 774" },
  ],
  [
    { title: "E 大调无词歌，柔板", composer: "门德尔松", workNumber: "Op.30 No.3" },
    { title: "A 大调无词歌，中板", composer: "门德尔松", workNumber: "Op.19b No.4" },
    { title: "威尼斯船歌，G 小调", composer: "门德尔松", workNumber: "Op.19b No.6" },
    { title: "B 小调圆舞曲", composer: "肖邦", workNumber: "Op.69 No.2" },
    { title: "亚麻色头发的少女", composer: "德彪西", workNumber: "L.117 No.8" },
    { title: "第一阿拉伯风格曲", composer: "德彪西", workNumber: "L.66 No.1" },
    { title: "第二阿拉伯风格曲", composer: "德彪西", workNumber: "L.66 No.2" },
    { title: "A 小调无词歌", composer: "门德尔松", workNumber: "Op.19b No.2" },
    { title: "E 大调无词歌，流动的行板", composer: "门德尔松", workNumber: "Op.19b No.1" },
    { title: "降 A 大调圆舞曲《告别》", composer: "肖邦", workNumber: "Op.69 No.1" },
    { title: "F 小调圆舞曲", composer: "肖邦", workNumber: "Op.70 No.2" },
    { title: "降 D 大调圆舞曲", composer: "肖邦", workNumber: "Op.70 No.3" },
    { title: "威尼斯船歌，升 F 小调", composer: "门德尔松", workNumber: "Op.30 No.6" },
    { title: "F 小调音乐瞬间", composer: "舒伯特", workNumber: "D.780 No.3" },
    { title: "降 A 大调音乐瞬间", composer: "舒伯特", workNumber: "D.780 No.2" },
    { title: "升 C 小调音乐瞬间", composer: "舒伯特", workNumber: "D.780 No.4" },
    { title: "G 小调夜曲", composer: "肖邦", workNumber: "Op.15 No.3" },
    { title: "春之歌", composer: "门德尔松", workNumber: "Op.62 No.6" },
    { title: "A 小调圆舞曲", composer: "肖邦", workNumber: "Op.34 No.2" },
    { title: "A 大调《军队波兰舞曲》", composer: "肖邦", workNumber: "Op.40 No.1" },
    { title: "梦幻曲", composer: "德彪西", workNumber: "L.68" },
    { title: "降 A 大调即兴曲", composer: "舒伯特", workNumber: "D.935 No.2 / Op.142 No.2" },
    { title: "E 小调夜曲", composer: "肖邦", workNumber: "Op.72 No.1" },
    { title: "F 小调夜曲", composer: "肖邦", workNumber: "Op.55 No.1" },
    { title: "降 E 大调夜曲", composer: "肖邦", workNumber: "Op.9 No.2" },
    { title: "降 B 小调夜曲", composer: "肖邦", workNumber: "Op.9 No.1" },
    { title: "小狗圆舞曲", composer: "肖邦", workNumber: "Op.64 No.1" },
    { title: "升 C 小调圆舞曲", composer: "肖邦", workNumber: "Op.64 No.2" },
    { title: "月光", composer: "德彪西", workNumber: "L.75 No.3" },
    { title: "降 E 大调即兴曲", composer: "舒伯特", workNumber: "D.899 No.2 / Op.90 No.2" },
  ],
];

function pieceLabel(stageIndex: number, partNumber: number) {
  const piece = stagePieces[stageIndex][partNumber - 1];
  return `${piece.title} - ${piece.composer}，${piece.workNumber}`;
}

function OfficialScoresPage({ isDark }: { isDark: boolean }) {
  const stages = [
    { name: "起步", description: "识谱与双手配合", image: bachCat },
    { name: "基础", description: "旋律与伴奏", image: mozartCat },
    { name: "进阶", description: "技术与乐句", image: beethovenCat },
    { name: "提高", description: "复调与曲式", image: chopinCat },
    { name: "综合", description: "完整作品演奏", image: lisztCat },
  ];
  const [stageIndex, setStageIndex] = useState(0);
  const [partNumber, setPartNumber] = useState(1);
  const [navigationRevision, setNavigationRevision] = useState(0);
  const navigationTarget = useRef(1);
  const partSections = useRef<(HTMLElement | null)[]>([]);
  const bannerIndex = (partNumber - 1) % 12;
  const bannerSource = [brickBanner, goldBanner, tealBanner, navyBanner, sageBanner, oliveBanner, roseBanner, plumBanner, lavenderBanner, blueBanner, ochreBanner, sandBanner][bannerIndex];
  const [expandedStage, setExpandedStage] = useState<number | null>(null);
  const [stageMenuOpen, setStageMenuOpen, stageDialog] = useAnimatedSheet();
  useEffect(() => {
    const dialog = stageDialog.current;
    if (stageMenuOpen && !dialog?.open) dialog?.showModal();
    if (!stageMenuOpen && dialog?.open) dialog.close();
  }, [stageMenuOpen]);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [playing, setPlaying] = useState(false);
  const audio = useRef<AudioContext | null>(null);
  const audioTimer = useRef<number | null>(null);
  const pathScroll = useRef<HTMLDivElement>(null);
  const scrollFrame = useRef<number | null>(null);
  const scrollInProgress = useRef(false);
  const holdTimer = useRef<number | null>(null);
  const longPress = useRef(false);
  const [scrolling, setScrolling] = useState(false);
  const [scrollUp, setScrollUp] = useState(false);
  const stopScrolling = () => {
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
    holdTimer.current = null;
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    scrollFrame.current = null;
    scrollInProgress.current = false;
    setScrolling(false);
  };
  useLayoutEffect(() => {
    stopScrolling();
    const container = pathScroll.current;
    const target = partSections.current[navigationTarget.current - 1];
    if (container) container.scrollTop = navigationTarget.current === 1 || !target ? 0 : target.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop;
    setScrollUp(false);
  }, [stageIndex, navigationRevision]);
  useEffect(() => () => {
    if (scrollFrame.current !== null) cancelAnimationFrame(scrollFrame.current);
    if (holdTimer.current !== null) window.clearTimeout(holdTimer.current);
  }, []);
  const jumpToEnd = () => {
    stopScrolling();
    const container = pathScroll.current;
    if (!container) return;
    container.scrollTop = scrollUp ? 0 : container.scrollHeight - container.clientHeight;
    setScrollUp(!scrollUp);
  };
  const scrollToEnd = () => {
    const container = pathScroll.current;
    if (!container || scrollInProgress.current) return;
    const start = container.scrollTop;
    const target = scrollUp ? 0 : container.scrollHeight - container.clientHeight;
    const distance = target - start;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches || Math.abs(distance) < 1) {
      container.scrollTop = target;
      setScrollUp(!scrollUp);
      return;
    }
    const duration = Math.max(1200, Math.min(5500, Math.abs(distance) / 6));
    let startTime: number | null = null;
    scrollInProgress.current = true;
    setScrolling(true);
    const animate = (timestamp: number) => {
      if (startTime === null) startTime = timestamp;
      const progress = Math.min(1, (timestamp - startTime) / duration);
      const eased = progress * progress * progress * (progress * (progress * 6 - 15) + 10);
      container.scrollTop = start + distance * eased;
      if (progress < 1) scrollFrame.current = requestAnimationFrame(animate);
      else {
        container.scrollTop = target;
        scrollFrame.current = null;
        scrollInProgress.current = false;
        setScrolling(false);
        setScrollUp(!scrollUp);
      }
    };
    scrollFrame.current = requestAnimationFrame(animate);
  };
  useEffect(() => () => {
    if (audioTimer.current) window.clearTimeout(audioTimer.current);
    void audio.current?.close();
  }, []);
  const playPreview = async () => { setMessage("此曲目尚未提供可用曲谱资源，暂时无法试听。你可以导入自己的 MusicXML 开始练习。"); };
  const discs: Record<string, string> = { wave: tuningForkDisc, star: metronomeDisc, music: headphonesDisc, tempo: batonDisc, notes: lyreDisc, triangle: triangleDisc };
  const secondDiscs: Record<string, string> = { wave: secondTuningForkDisc, star: secondMetronomeDisc, music: secondHeadphonesDisc, tempo: secondBatonDisc, notes: secondLyreDisc, triangle: secondTriangleDisc };
  const thirdDiscs: Record<string, string> = { wave: thirdTuningForkDisc, star: thirdMetronomeDisc, music: thirdHeadphonesDisc, tempo: thirdBatonDisc, notes: thirdLyreDisc, triangle: thirdTriangleDisc };
  const fourthDiscs: Record<string, string> = { wave: fourthTuningForkDisc, star: fourthMetronomeDisc, music: fourthHeadphonesDisc, tempo: fourthBatonDisc, notes: fourthLyreDisc, triangle: fourthTriangleDisc };
  const fifthDiscs: Record<string, string> = { wave: fifthTuningForkDisc, star: fifthMetronomeDisc, music: fifthHeadphonesDisc, tempo: fifthBatonDisc, notes: fifthLyreDisc, triangle: fifthTriangleDisc };
  const sixthDiscs: Record<string, string> = { wave: sixthTuningForkDisc, star: sixthMetronomeDisc, music: sixthHeadphonesDisc, tempo: sixthBatonDisc, notes: sixthLyreDisc, triangle: sixthTriangleDisc };
  const seventhDiscs: Record<string, string> = { wave: seventhTuningForkDisc, star: seventhMetronomeDisc, music: seventhHeadphonesDisc, tempo: seventhBatonDisc, notes: seventhLyreDisc, triangle: seventhTriangleDisc };
  const eighthDiscs: Record<string, string> = { wave: eighthTuningForkDisc, star: eighthMetronomeDisc, music: eighthHeadphonesDisc, tempo: eighthBatonDisc, notes: eighthLyreDisc, triangle: eighthTriangleDisc };
  const ninthDiscs: Record<string, string> = { wave: ninthTuningForkDisc, star: ninthMetronomeDisc, music: ninthHeadphonesDisc, tempo: ninthBatonDisc, notes: ninthLyreDisc, triangle: ninthTriangleDisc };
  const tenthDiscs: Record<string, string> = { wave: tenthTuningForkDisc, star: tenthMetronomeDisc, music: tenthHeadphonesDisc, tempo: tenthBatonDisc, notes: tenthLyreDisc, triangle: tenthTriangleDisc };
  const eleventhDiscs: Record<string, string> = { wave: eleventhTuningForkDisc, star: eleventhMetronomeDisc, music: eleventhHeadphonesDisc, tempo: eleventhBatonDisc, notes: eleventhLyreDisc, triangle: eleventhTriangleDisc };
  const twelfthDiscs: Record<string, string> = { wave: twelfthTuningForkDisc, star: twelfthMetronomeDisc, music: twelfthHeadphonesDisc, tempo: twelfthBatonDisc, notes: twelfthLyreDisc, triangle: twelfthTriangleDisc };
  const discSets = [discs, secondDiscs, thirdDiscs, fourthDiscs, fifthDiscs, sixthDiscs, seventhDiscs, eighthDiscs, ninthDiscs, tenthDiscs, eleventhDiscs, twelfthDiscs];
  const recordPlayers = [brickRecordPlayer, goldRecordPlayer, tealRecordPlayer, navyRecordPlayer, sageRecordPlayer, oliveRecordPlayer, roseRecordPlayer, plumRecordPlayer, lavenderRecordPlayer, blueRecordPlayer, ochreRecordPlayer, sandRecordPlayer];
  const discSource = (kind: string, displayedPart: number) => {
    return discSets[(displayedPart - 1) % discSets.length][kind];
  };
  const node = (id: string, kind: string, position: string, green = false, displayedPart = partNumber) => <div className={`relative flex h-[94px] items-start justify-center ${position}`}>
    {discSource(kind, displayedPart) ? <button type="button" aria-label={id} aria-pressed={selectedNode === id} onClick={() => { setSelectedNode(selectedNode === id ? null : id); setMessage(""); }} className="flex h-24 w-24 cursor-pointer items-center justify-center rounded-full touch-manipulation transition-transform duration-75 active:translate-y-[5px] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current motion-reduce:transition-none"><img src={discSource(kind, displayedPart)} alt="" loading="lazy" className="h-full w-full object-contain" /></button> :
    <button type="button" aria-label={id} aria-pressed={selectedNode === id} onClick={() => { setSelectedNode(selectedNode === id ? null : id); setMessage(""); }} className={`relative flex h-[72px] w-[76px] cursor-pointer items-center justify-center overflow-hidden rounded-[50%] border-b-[9px] transition-[transform,border-width] duration-75 active:translate-y-[5px] active:border-b-4 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-current ${green ? "border-[#48aa16] bg-[#67db23]" : "border-[#cb60a3] bg-[#f781cb]"}`}>
      <span className="pointer-events-none absolute inset-1 rounded-[50%] bg-[linear-gradient(135deg,transparent_20%,rgba(255,255,255,0.25)_20%,rgba(255,255,255,0.25)_40%,transparent_40%,transparent_54%,rgba(255,255,255,0.18)_54%,rgba(255,255,255,0.18)_67%,transparent_67%)]" />
      <span className="relative"><ScorePathSymbol kind={kind} /></span>
    </button>}
  </div>;
  return <div className="relative flex h-full min-h-0 flex-col px-5 pt-4">
    <div className="relative z-10 flex aspect-[25/6] w-full shrink-0 touch-manipulation text-[#fff4dd] transition-transform duration-75 has-[>button:active]:translate-y-[3px] motion-reduce:transition-none">
      <img src={bannerSource} alt="" className="pointer-events-none absolute inset-0 h-full w-full object-contain" />
      <button type="button" aria-label="选择阶段和部分" onClick={() => { setExpandedStage(null); setStageMenuOpen(true); }} className="relative my-[2%] ml-[2%] flex min-w-0 flex-1 cursor-pointer flex-col justify-center rounded-l-[15px] px-4 pb-1 text-left active:bg-white/10 focus-visible:outline-2 focus-visible:outline-current"><p className="text-[15px] font-bold opacity-80">第 {stageIndex + 1} 阶段，第 {partNumber} 部分</p><h1 className="mt-1 line-clamp-3 w-full text-[14px] font-bold leading-4">{pieceLabel(stageIndex, partNumber)}</h1></button>
      <button type="button" aria-label={playing ? "停止曲目试听" : "试听曲目旋律"} aria-pressed={playing} onClick={playPreview} className="relative my-[2%] mr-[2%] w-[15%] shrink-0 cursor-pointer rounded-r-[15px] active:bg-white/15 focus-visible:outline-2 focus-visible:outline-current">
      </button>
    </div>
    <div ref={pathScroll} onWheel={stopScrolling} onTouchStart={stopScrolling} onPointerDown={stopScrolling} onScroll={(event) => {
      const container = event.currentTarget;
      const top = container.getBoundingClientRect().top;
      let visiblePart = 1;
      partSections.current.forEach((section, index) => { if (section && section.getBoundingClientRect().top <= top + 4) visiblePart = index + 1; });
      setPartNumber(visiblePart);
      if (!scrollInProgress.current) {
        if (container.scrollTop <= 2) setScrollUp(false);
        else if (container.scrollHeight - container.clientHeight - container.scrollTop <= 2) setScrollUp(true);
      }
    }} className="min-h-0 flex-1 overflow-y-auto overscroll-contain pb-20 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
    <div className="relative mx-auto max-w-[360px] pt-8">
      {Array.from({ length: 30 }, (_, offset) => {
        const displayedPart = offset + 1;
        const recordPlayerSource = recordPlayers[(displayedPart - 1) % recordPlayers.length];
        return <section ref={(element) => { partSections.current[offset] = element; }} key={`${stageIndex}-${displayedPart}`} className="relative" aria-label={`第 ${displayedPart} 部分`}>
          {offset > 0 && <div className="mb-10 flex scroll-mt-[100px] items-center gap-3 text-[#aaa]"><span className={`h-[2px] flex-1 ${isDark ? "bg-white/15" : "bg-[#e5e5e5]"}`} /><h2 className="max-w-[78%] text-center text-[16px] font-bold leading-6">{pieceLabel(stageIndex, displayedPart)}</h2><span className={`h-[2px] flex-1 ${isDark ? "bg-white/15" : "bg-[#e5e5e5]"}`} /></div>}
          {[
            { label: "节奏练习", kind: "wave", position: "translate-x-0" },
            { label: "基础练习", kind: "star", position: "-translate-x-[48px]" },
            { label: "单音练习", kind: "music", position: "-translate-x-[72px]" },
            { label: "速度练习", kind: "tempo", position: "translate-x-0" },
            { label: "旋律练习", kind: "notes", position: "translate-x-[48px]" },
            { label: "综合练习", kind: "triangle", position: "translate-x-0" },
          ].map((block) => <div key={block.kind}>{node(`第 ${displayedPart} 部分：${block.label}`, block.kind, block.position, offset > 0, displayedPart)}</div>)}
          {offset === 0 && <img src={aiIcon} alt="练琴小猫" className="pointer-events-none absolute right-0 top-[148px] h-[140px] w-[120px] object-contain" />}
      <div className="flex flex-col items-center pt-2 pb-12">
        <button type="button" aria-label={`第 ${displayedPart} 部分：曲目挑战`} onClick={() => { setSelectedNode(`第 ${displayedPart} 部分：曲目挑战`); setMessage(""); }} className="h-[110px] w-[110px] cursor-pointer active:translate-y-1 focus-visible:outline-2 focus-visible:outline-current">{recordPlayerSource ? <img src={recordPlayerSource} alt="" className="h-full w-full object-contain" /> : <svg viewBox="0 0 110 110" className="h-full w-full" aria-hidden="true"><rect x="2" y="14" width="106" height="94" rx="9" fill="#e8e8e8" /><rect x="10" y="9" width="90" height="91" rx="8" fill="#cb60a3" /><rect x="10" y="5" width="90" height="86" rx="8" fill="#f781cb" /><circle cx="48" cy="45" r="35" fill="#414141" /><path d="m22 68 48-48" stroke="#535353" strokeWidth="13" /><circle cx="48" cy="45" r="9" fill="#f781cb" /><circle cx="48" cy="45" r="4" fill="#ffd4ec" /><path d="M89 11v41L76 68" stroke="#c84099" strokeWidth="8" strokeLinecap="round" /><circle cx="91" cy="79" r="4" fill="#ffd4ec" /></svg>}</button>
        <div className="mt-2 flex gap-1 text-[#e5e5e5]" aria-label="尚未获得挑战星星">{[0, 1, 2].map((star) => <svg key={star} viewBox="0 0 48 48" className={`h-6 w-6 ${star === 1 ? "translate-y-2" : ""}`} fill="currentColor" aria-hidden="true"><path d="m24 3 6 13 14 2-10 10 2 15-12-7-12 7 2-15L4 18l14-2Z" /></svg>)}</div>
      </div>
        </section>;
      })}
    </div>
    </div>
    {selectedNode && <div role="status" className={`absolute inset-x-5 bottom-3 z-20 rounded-[17px] border-2 p-4 ${isDark ? "border-white/15 bg-[#252525]" : "border-[#e5e5e5] bg-white"}`}><div className="flex items-center justify-between"><h3 className="text-[18px] font-bold">{selectedNode}</h3><button type="button" aria-label="关闭练习信息" onClick={() => { setSelectedNode(null); setMessage(""); }} className="flex h-8 w-8 cursor-pointer items-center justify-center text-[24px] text-[#aaa]">×</button></div><p className="mt-2 text-[13px] text-[#999]">{message || "此曲目待曲谱资源；导入自己的 MusicXML 或载入示例曲谱即可练习。"}</p></div>}
    {!selectedNode && <button type="button" aria-label={scrollUp ? "滚动到顶部" : "滚动到底部"} aria-busy={scrolling} onPointerDown={(event) => {
      if (event.button !== 0) return;
      stopScrolling();
      longPress.current = false;
      event.currentTarget.setPointerCapture(event.pointerId);
      holdTimer.current = window.setTimeout(() => { holdTimer.current = null; longPress.current = true; scrollToEnd(); }, 220);
    }} onPointerUp={stopScrolling} onPointerCancel={() => { longPress.current = true; stopScrolling(); }} onLostPointerCapture={stopScrolling} onContextMenu={(event) => event.preventDefault()} onClick={(event) => {
      if (longPress.current && event.detail !== 0) { longPress.current = false; return; }
      longPress.current = false;
      jumpToEnd();
    }} className={`absolute right-5 bottom-3 z-10 touch-none select-none flex h-12 w-12 cursor-pointer items-center justify-center rounded-[15px] border-2 border-b-[5px] text-[#67db23] ${pressFeedback} ${isDark ? "border-white/15 bg-[#252525]" : "border-[#e5e5e5] bg-white"}`}><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={scrollUp ? "rotate-180" : ""}><path d="M12 3v16m-7-7 7 7 7-7" /></svg></button>}
    {!selectedNode && message && <p role="status" className="mt-3 text-[13px] text-[#999]">{message}</p>}
    <dialog ref={stageDialog} aria-labelledby="stage-menu-title" onCancel={(event) => { event.preventDefault(); setStageMenuOpen(false); }} onClose={() => setStageMenuOpen(false)} className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto border-0 p-0 font-sans [scrollbar-width:none] [&::-webkit-scrollbar]:hidden backdrop:bg-black/40 backdrop:transition-colors backdrop:duration-[260ms] data-[closing=true]:backdrop:bg-black/0 motion-reduce:backdrop:transition-none open:animate-settings-sheet motion-reduce:animate-none ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#4b4b4b]"}`}>
      <div className="mx-auto min-h-dvh w-full max-w-none pb-[max(28px,env(safe-area-inset-bottom))] sm:max-w-[680px]">
        <header className={`sticky top-0 z-20 border-b-2 pt-[var(--yinban-top-inset)] ${isDark ? "border-white/10 bg-[#191919]" : "border-[#e5e5e5] bg-white"}`}><div className="relative flex h-14 items-center justify-center"><button type="button" aria-label="关闭阶段目录" onClick={() => setStageMenuOpen(false)} className={`absolute left-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full text-[#aaa] focus-visible:outline-2 focus-visible:outline-current ${isDark ? "active:bg-white/15" : "active:bg-black/10"}`}><svg width="27" height="27" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true"><path d="m4 4 16 16M20 4 4 20" /></svg></button><h2 id="stage-menu-title" className="text-[21px] font-bold">音乐</h2></div></header>
        <div className="space-y-5 px-4 pt-5">
          {stages.map((stage, index) => <section key={stage.name} className={`overflow-hidden rounded-[20px] border-2 border-b-[6px] touch-manipulation transition-[transform,border-width,padding] duration-75 has-[>button:active]:translate-y-1 has-[>button:active]:border-b-2 has-[>button:active]:pb-1 motion-reduce:transition-none ${isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
            <button type="button" aria-expanded={expandedStage === index} aria-controls={`stage-parts-${index}`} onClick={() => setExpandedStage(expandedStage === index ? null : index)} className="block w-full cursor-pointer text-left focus-visible:outline-2 focus-visible:outline-current">
              <div className="relative flex h-[142px] items-center overflow-hidden">
                <div aria-hidden="true" className="absolute inset-x-0 top-9 flex flex-col gap-3">{[0, 1, 2, 3, 4].map((line) => <div key={line} className={`h-[2px] ${isDark ? "bg-white/15" : "bg-[#ddd]"}`} />)}</div>
                <div aria-hidden="true" className="relative ml-5 flex w-[62%] items-center gap-3 text-[#666]">
                  {index === 0 ? <div className="flex w-full flex-wrap gap-3"><span className="translate-y-4 rounded bg-[#67db23] px-3 py-0.5 text-[21px] font-bold text-white">E</span><span className="-translate-y-3 rounded bg-[#ffb329] px-3 py-0.5 text-[21px] font-bold text-white">D</span><span className="translate-y-1 rounded bg-[#f781cb] px-5 py-0.5 text-[21px] font-bold text-white">A</span></div> : <><span className="text-[76px] leading-none">𝄞</span><span className="text-[45px]">{index === 3 ? "♭" : index === 4 ? "♯" : "♩"}</span><span className="text-[48px]">{index >= 2 ? "♫" : "♪"}</span></>}
                </div>
                <img src={stage.image} alt="" loading="lazy" className={`absolute right-2 top-3 h-[128px] w-[118px] object-contain ${index % 2 ? "rotate-6" : "-rotate-6"}`} />
              </div>
              <div className="px-4 pt-4 pb-5"><h3 className="text-[25px] font-bold">第 {index + 1} 阶段</h3><p className="mt-2 text-[18px] text-[#999]">{stage.name}：{stage.description}</p>
                {stageIndex === index ? <div className="mt-4"><div aria-label={`${stage.name}曲谱资源待接入`} className={`h-4 overflow-hidden rounded-full ${isDark ? "bg-white/10" : "bg-[#e5e5e5]"}`}><div className="h-full w-0 rounded-full bg-[#67db23]" /></div><p className="mt-2 text-[14px] font-bold text-[#67db23]">当前：第 {partNumber} 部分 · 选择部分</p></div> : <p className="mt-3 text-[15px] font-bold text-[#67db23]">选择此阶段</p>}
              </div>
            </button>
            {expandedStage === index && <div id={`stage-parts-${index}`} className={`grid grid-cols-5 gap-2 border-t-2 p-4 ${isDark ? "border-white/10" : "border-[#e5e5e5]"}`}>
              {Array.from({ length: 30 }, (_, part) => <button key={part} type="button" aria-label={`第${index + 1}阶段，第${part + 1}部分，6个练习板块`} aria-pressed={stageIndex === index && partNumber === part + 1} onClick={() => { navigationTarget.current = part + 1; setNavigationRevision((previous) => previous + 1); setStageIndex(index); setPartNumber(part + 1); setSelectedNode(null); setMessage(""); setStageMenuOpen(false); }} className={`h-11 cursor-pointer rounded-[10px] border-2 border-b-[4px] text-[16px] font-bold ${pressFeedback} ${stageIndex === index && partNumber === part + 1 ? "border-[#48aa16] bg-[#67db23] text-white" : isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>{part + 1}</button>)}
            </div>}
          </section>)}
        </div>
      </div>
    </dialog>
  </div>;
}

function MyScoresPage({ isDark }: { isDark: boolean }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState("");

  return <section className="flex min-h-full flex-col items-center justify-center px-4 py-8">
    <input ref={fileInput} type="file" accept="image/*,.pdf,.musicxml,.mxl,.xml" className="hidden" aria-label="选择曲谱文件或图片" onChange={(event) => {
      setFileName(event.currentTarget.files?.[0]?.name || "");
      event.currentTarget.value = "";
    }} />
    <button type="button" aria-label="上传文件、图片或拍照识谱，开启你的专属陪练" onClick={() => fileInput.current?.click()} className="group relative block w-full max-w-[400px] cursor-pointer touch-manipulation rounded-[18px] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#67db23]">
      <img src={scoresUploadNormal} alt="作曲家们陪你练琴：上传文件、图片或拍照识谱，开启你的专属陪练吧！" draggable={false} className="block h-auto w-full select-none group-active:opacity-0" />
      <img src={scoresUploadPressed} alt="" aria-hidden="true" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full select-none object-contain opacity-0 group-active:opacity-100" />
    </button>
    {fileName && <p role="status" className={`mt-5 max-w-full break-all text-center text-sm leading-6 ${isDark ? "text-[#aaa]" : "text-[#777]"}`}>已选择：{fileName}<br />曲谱识别功能暂未接入。</p>}
  </section>;
}

function MusicAssistantPage({ isDark, streak, practiceCount }: { isDark: boolean; streak: number; practiceCount: number }) {
  const { state } = useYinban();
  const stats = summarizeHistory(state.history);
  const [speaking, setSpeaking] = useState(false);
  const [analysis, setAnalysis] = useState("");
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => () => {
    if (utterance.current) {
      utterance.current.onstart = null;
      utterance.current.onend = null;
      utterance.current.onerror = null;
      window.speechSynthesis?.cancel();
    }
  }, []);

  function analyzePractice() {
    const result = practiceCount === 0
      ? "还没有找到你的练琴打卡记录。今天先练习十分钟，完成第一次打卡吧！"
      : streak > 0
        ? `你已经连续练琴 ${streak} 天啦！建议今天先慢练，再完整演奏一遍，保持这个好习惯。`
        : `你已有 ${practiceCount} 个练琴打卡日。重新开始不必着急，今天从十分钟慢练开始吧！`;
    const detail = stats.accuracy === null ? "" : ` 已评分音符的首次正确率是 ${stats.accuracy}%。建议把有问题的小节拆开，在练习设置中降低速度，重练后再比较记录。`;
    const fullResult = result + detail;
    setAnalysis(fullResult);
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
    const speech = new SpeechSynthesisUtterance(fullResult);
    speech.lang = "zh-CN";
    speech.rate = 0.95;
    speech.onstart = () => setSpeaking(true);
    speech.onend = () => setSpeaking(false);
    speech.onerror = () => setSpeaking(false);
    utterance.current = speech;
    window.speechSynthesis.speak(speech);
  }

  return <section className="flex min-h-full flex-col px-7 pb-7 pt-5">
    <div className="flex flex-1 flex-col items-center justify-center gap-7 py-8">
      <div className={`music-assistant-orbit relative flex aspect-square w-[min(68vw,280px)] shrink-0 items-center justify-center rounded-full border-[3px] ${isDark ? "border-white/25" : "border-[#d9d9d9]"}`} data-speaking={speaking}>
        <span aria-hidden="true" className="music-assistant-wave absolute -inset-[3px] rounded-full border-2 border-[#67db23]" />
        <span aria-hidden="true" className="music-assistant-wave music-assistant-wave-delayed absolute -inset-[3px] rounded-full border-2 border-[#67db23]" />
        <img src={aiIcon} alt="黑白键3D小猫" className="relative h-[85%] w-[85%] object-contain" />
      </div>
      <div className="w-full max-w-[320px] text-center">
        <h1 className="text-[23px] font-bold">黑白键AI</h1>
        <p role="status" className={`mt-3 text-[15px] leading-7 ${isDark ? "text-[#aaa]" : "text-[#777]"}`}>{analysis || "让我陪你一起，把每一次练琴变成进步。"}</p>
        <p className={`mt-2 text-xs ${isDark ? "text-[#888]" : "text-[#888]"}`}>{speaking ? "小猫正在说话…" : analysis ? "基于本地练习记录的规则建议" : "你的专属练琴小伙伴"}</p>
      </div>
    </div>
    <button type="button" onClick={analyzePractice} className="min-h-[58px] w-full cursor-pointer touch-manipulation rounded-[18px] border-2 border-b-[6px] border-[#49a619] bg-[#67db23] px-4 text-[17px] font-bold text-[#173b09] transition-[transform,border-width] duration-75 active:translate-y-[4px] active:border-b-2 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[#67db23] motion-reduce:transition-none">分析我的练琴记录</button>
  </section>;
}

function AccountPage({ isDark, streak, practiceCount, avatarSrc, courseImage, onAction }: { isDark: boolean; streak: number; practiceCount: number; avatarSrc: string; courseImage: string; onAction: (action: string) => void }) {
  const { state } = useYinban();
  const stats = summarizeHistory(state.history);
  const outline = isDark ? "border-white/15" : "border-[#e5e5e5]";
  const button = `flex h-12 cursor-pointer items-center justify-center gap-2 rounded-[15px] border-2 border-b-[5px] text-[17px] font-bold focus-visible:outline-2 focus-visible:outline-current ${outline} ${pressFeedback}`;
  return <>
    <div className={`flex h-[210px] items-end justify-center overflow-hidden pt-5 ${isDark ? "bg-[#252525]" : "bg-[#e9e9e9]"}`}>
      <img src={avatarSrc} alt="黑白键小猫头像" className="h-[205px] w-[205px] object-contain" />
    </div>
    <div className="px-5 pb-8 pt-5">
      <p className="text-[14px] font-bold text-[#aaa]">@HEIBAIKEY · 本机档案</p>
      <div className="my-4 grid grid-cols-3 gap-4">
        <button type="button" onClick={() => onAction("课程")} className="cursor-pointer text-left"><div className="flex h-8 items-center gap-2"><img src={courseImage} alt="" className="h-7 w-7 object-contain" /><span className="text-[19px] font-bold">0</span></div><span className="text-[15px] font-medium text-[#aaa]">课程</span></button>
        {["关注", "关注者"].map((label) => <button key={label} type="button" onClick={() => onAction(label)} className="cursor-pointer text-left"><div className="flex h-8 items-center text-[19px] font-bold">0</div><span className="text-[15px] font-medium text-[#aaa]">{label}</span></button>)}
      </div>
      <div className="flex gap-3"><button type="button" onClick={() => onAction("添加好友")} className={`${button} flex-1`}><AccountSymbol kind="person" />添加好友</button><button type="button" onClick={() => onAction("我的二维码")} aria-label="我的二维码" className={`${button} w-12 shrink-0`}><img src={isDark ? qrDarkIcon : qrLightIcon} alt="" className="h-7 w-7 object-contain" /></button></div>
      <section className="relative mt-5 overflow-hidden rounded-[20px] border-2 border-[#48aa16] bg-[#67db23] p-4 text-white">
        <div className="relative z-10 min-h-[104px] pr-24"><h2 className="text-[21px] font-bold leading-8">练琴解锁全新<br />专属装扮！</h2><p className="mt-3 text-[13px] font-medium text-[#fff1a6]">持续练习 · 收获成长</p></div>
        <img src={aiIcon} alt="" className="absolute right-1 top-3 h-32 w-28 object-contain" />
        <button type="button" onClick={() => onAction("装扮")} className={`relative z-10 mt-3 h-12 w-full cursor-pointer rounded-[14px] border-b-[5px] border-[#ddd] bg-white text-[18px] font-bold text-[#67db23] ${pressFeedback}`}>去看看</button>
      </section>
      <section className="mt-8"><h2 className="mb-4 text-[15px] font-medium text-[#aaa]">概览</h2>
        <div className="grid grid-cols-2 gap-x-4 gap-y-4 text-[17px] font-bold">
          <button type="button" onClick={() => onAction("连胜")} className="flex cursor-pointer items-center gap-2 text-left"><StreakNote active={streak > 0} isDark={isDark} className="h-7 w-7" /><span className={streak > 0 ? "" : "text-[#aaa]"}>{streak} 天</span></button>
          <div className="flex items-center gap-2"><img src={isDark ? experienceDarkIcon : experienceLightIcon} alt="" className="h-7 w-7 object-contain" /><span>{stats.completed * 10} 经验</span></div>
          <div className="flex items-center gap-2"><img src={isDark ? leaderboardDarkIcon : leaderboardLightIcon} alt="" className="h-7 w-7 object-contain" /><span>未上榜</span></div>
          <div className="flex items-center gap-2"><img src={isDark ? checkinDarkIcon : checkinLightIcon} alt="" className="h-7 w-7 object-contain" /><span>{practiceCount} 天打卡</span></div>
        </div>
      </section>
      <section className="mt-8">
        <button type="button" onClick={() => onAction("独家装扮")} className="mb-4 flex w-full cursor-pointer items-center justify-between text-[15px] font-medium text-[#aaa]"><span>独家装扮</span><span className="text-[25px] leading-none">›</span></button>
        <div className="grid grid-cols-4 gap-3">
          {[{ name: "巴赫", image: bachOutfit }, { name: "莫扎特", image: mozartOutfit }, { name: "猫赫", image: bachCat }, { name: "莫扎猫", image: mozartCat }].map((outfit) => <div key={outfit.name} aria-label={`${outfit.name}，装扮尚未解锁`} className={`relative flex aspect-square items-center justify-center overflow-hidden rounded-full border-[4px] border-b-[6px] ${isDark ? "border-white/10 bg-white/5" : "border-[#eee] bg-[#e7e7e7]"}`}>
            <img src={outfit.image} alt="" loading="lazy" decoding="async" className="absolute inset-0 h-full w-full object-contain opacity-50" />
            <span className={`relative flex h-8 w-8 items-center justify-center rounded-full ${isDark ? "bg-[#292929]/85" : "bg-white/85"}`}><AccountSymbol kind="lock" className="h-5 w-5 text-[#aaa]" /></span>
          </div>)}
        </div>
      </section>
    </div>
  </>;
}

export default function App() {
  const { state } = useYinban();
  const stats = summarizeHistory(state.history);
  const [customAvatar, setCustomAvatar] = useState(() => { try { return localStorage.getItem("music-profile-avatar"); } catch { return null; } });
  useEffect(() => { const update = () => setCustomAvatar(localStorage.getItem("music-profile-avatar")); window.addEventListener("yinban-profile-update", update); return () => window.removeEventListener("yinban-profile-update", update); }, []);
  const [savedOutfit, setSavedOutfit] = useState(() => { try { return localStorage.getItem("music-outfit") || "plain"; } catch { return "plain"; } });
  const outfitUnlocked = (id: string) => id === "plain" || stats.completed >= wardrobeOutfits.findIndex(outfit => outfit.id === id) * 3;
  const [selectedCourse, setSelectedCourse] = useState<string | null>(() => {
    try {
      const saved = localStorage.getItem("music-selected-course");
      return saved && courseImages[saved.split("-").pop() || ""] ? saved : null;
    } catch { return null; }
  });
  const selectedCourseImage = courseImages[selectedCourse?.split("-").pop() || "钢琴"] || pianoCourse;
  useEffect(() => {
    if (selectedCourse) {
      try { localStorage.setItem("music-selected-course", selectedCourse); } catch {}
      const instrument = instrumentForCourse(selectedCourse);
      window.webkit?.messageHandlers?.yinban?.postMessage({ action: "preferences", instrument });
    }
  }, [selectedCourse]);
  const [displayName, setDisplayName] = useState(() => {
    try { return localStorage.getItem("music-display-name") || "名字"; } catch { return "名字"; }
  });
  useEffect(() => { try { localStorage.setItem("music-display-name", displayName); } catch {} }, [displayName]);
  const [activeTab, setActiveTab] = useState("library");
  const [savedAvatar, setSavedAvatar] = useState(() => {
    try { return localStorage.getItem("music-avatar") === "portrait" ? "portrait" : "mascot"; } catch { return "mascot"; }
  });
  const [draftAvatar, setDraftAvatar] = useState(savedAvatar);
  const [previewOutfitId, setPreviewOutfitId] = useState("plain");
  const [wardrobeOpen, setWardrobeOpen, wardrobeDialog] = useAnimatedSheet();
  const [wardrobeTab, setWardrobeTab] = useState("outfits");
  const [wardrobeMessage, setWardrobeMessage] = useState("");
  const [showOutfitProgress, setShowOutfitProgress, outfitProgressDialog] = useAnimatedSheet();
  useEffect(() => {
    const dialog = outfitProgressDialog.current;
    if (showOutfitProgress && !dialog?.open) {
      dialog?.showModal();
      if (dialog) dialog.scrollTop = 0;
    }
    if (!showOutfitProgress && dialog?.open) dialog.close();
  }, [showOutfitProgress]);
  const previewOutfit = wardrobeOutfits.find((outfit) => outfit.id === previewOutfitId) || wardrobeOutfits[0];
  const previewLocked = wardrobeTab === "outfits" && !outfitUnlocked(previewOutfit.id);
  const selectedOutfitImage = savedOutfit !== "plain" && outfitUnlocked(savedOutfit) ? wardrobeOutfits.find(outfit => outfit.id === savedOutfit)?.image : null;
  const draftAvatarImage = draftAvatar === "portrait" ? accountLightIcon : aiIcon;
  useEffect(() => { try { localStorage.setItem("music-avatar", savedAvatar); } catch {} }, [savedAvatar]);
  useEffect(() => {
    const dialog = wardrobeDialog.current;
    if (wardrobeOpen && !dialog?.open) dialog?.showModal();
    if (!wardrobeOpen && dialog?.open) dialog.close();
  }, [wardrobeOpen]);
  const [accountScrolled, setAccountScrolled] = useState(false);
  const mainScroll = useRef<HTMLElement>(null);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const accountMenu = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    if (mainScroll.current) mainScroll.current.scrollTop = 0;
    setAccountScrolled(false);
  }, [activeTab]);
  useEffect(() => {
    if (accountMenuOpen && !accountMenu.current?.open) accountMenu.current?.showModal();
    if (!accountMenuOpen && accountMenu.current?.open) accountMenu.current.close();
  }, [accountMenuOpen]);
  const [historyOpen, setHistoryOpen, historyDialog] = useAnimatedSheet();
  const [settingsOpen, setSettingsOpen, settingsDialog] = useAnimatedSheet();
  const [settingsDetail, setSettingsDetail] = useState<string | null>(null);
  const [detailOrigin, setDetailOrigin] = useState<"account" | "settings">("settings");
  const settingsScrollPosition = useRef(0);
  useLayoutEffect(() => {
    if (settingsDialog.current) settingsDialog.current.scrollTop = settingsDetail ? 0 : settingsScrollPosition.current;
  }, [settingsDetail]);
  function openSettingsDetail(title: string) {
    settingsScrollPosition.current = settingsDialog.current?.scrollTop ?? 0;
    setDetailOrigin("settings");
    setSettingsDetail(title);
  }
  function accountAction(action: string) {
    if (action === "装扮" || action === "独家装扮") {
      setDraftAvatar(savedAvatar);
      setPreviewOutfitId(outfitUnlocked(savedOutfit) ? savedOutfit : "plain");
      setShowOutfitProgress(false);
      setWardrobeTab("outfits");
      setWardrobeMessage("");
      setWardrobeOpen(true);
      return;
    }
    if (action === "连胜") {
      const date = new Date();
      setMonthDirection(0);
      setVisibleMonth(new Date(date.getFullYear(), date.getMonth(), 1));
      setHistoryOpen(true);
      return;
    }
    settingsScrollPosition.current = 0;
    setDetailOrigin("account");
    setSettingsDetail(action);
    setSettingsOpen(true);
  }
  const [monthDirection, setMonthDirection] = useState(0);
  const monthTouch = useRef<{ x: number; y: number } | null>(null);
  const [visibleMonth, setVisibleMonth] = useState(() => {
    const date = new Date();
    return new Date(date.getFullYear(), date.getMonth(), 1);
  });
  const year = visibleMonth.getFullYear();
  const month = visibleMonth.getMonth();
  const monthDays = new Date(year, month + 1, 0).getDate();
  const firstWeekday = visibleMonth.getDay();

  useEffect(() => {
    const dialog = settingsDialog.current;
    if (settingsOpen && !dialog?.open) {
      dialog?.showModal();
      if (dialog) dialog.scrollTop = 0;
    }
    if (!settingsOpen && dialog?.open) dialog.close();
    if (!settingsOpen) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = overflow; };
  }, [settingsOpen]);

  function changeMonth(direction: number) {
    setMonthDirection(direction);
    setVisibleMonth((previous) => new Date(previous.getFullYear(), previous.getMonth() + direction, 1));
  }

  useEffect(() => {
    const dialog = historyDialog.current;
    if (historyOpen && !dialog?.open) {
      dialog?.showModal();
      if (dialog) dialog.scrollTop = 0;
    }
    if (!historyOpen && dialog?.open) dialog.close();
    if (!historyOpen) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = overflow; };
  }, [historyOpen]);

  function openHistory() {
    const date = new Date();
    setMonthDirection(0);
    setVisibleMonth(new Date(date.getFullYear(), date.getMonth(), 1));
    setActiveTab("practice");
    setHistoryOpen(true);
  }
  const [today, setToday] = useState(currentPracticeDay);
  const practice = { count: stats.practiceDays };
  const streak = stats.streak;
  const historyStreak = streak;
  const monthStart = Date.UTC(year, month, 1) / 86400000;
  const monthlyPracticeDays = Array.from(stats.days).filter(day => day >= monthStart && day < monthStart + monthDays).length;
  const elapsedMonthDays = Math.max(0, Math.min(monthDays, today - monthStart + 1));
  const missedPracticeDays = elapsedMonthDays - monthlyPracticeDays;

  useEffect(() => {
    const timer = window.setInterval(() => setToday(currentPracticeDay()), 30000);
    return () => window.clearInterval(timer);
  }, []);

  const [isDark, setIsDark] = useState(() => {
    try {
      return localStorage.getItem("sheet-music-theme") === "dark";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem("sheet-music-theme", isDark ? "dark" : "light");
    } catch {
      return;
    }
    window.webkit?.messageHandlers?.yinban?.postMessage({ action: "theme", isDark });
  }, [isDark]);

  return (
    <div className={`flex min-h-dvh justify-center font-sans transition-colors duration-200 ${isDark ? "bg-[#0a0a0a] text-white" : "bg-[#f5f5f5] text-black"}`}>
      <div className={`relative flex h-dvh w-full max-w-none sm:max-w-[680px] flex-col overflow-hidden transition-colors duration-200 sm:shadow-[0_0_50px_rgba(0,0,0,0.04)] ${isDark ? "bg-[#141414]" : "bg-white"}`}>
        <header className={`relative z-20 flex shrink-0 items-center justify-between px-4 pt-[var(--yinban-top-inset)] ${activeTab === "account" ? `border-b pb-3 ${accountScrolled ? isDark ? "border-white/10 bg-[#141414]" : "border-[#e5e5e5] bg-white" : isDark ? "border-transparent bg-[#252525]" : "border-transparent bg-[#e9e9e9]"}` : ""}`}>
          {activeTab === "account" ? (
            <>
              <span className="flex h-11 min-w-0 items-center truncate pl-2 text-[23px] font-bold">{displayName || "名字"}</span>
              <div className="flex shrink-0 items-center gap-1">
                <button type="button" aria-label="装扮" onClick={() => accountAction("装扮")} className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current">
                  <img src={isDark ? outfitDarkIcon : outfitLightIcon} alt="" className="h-8 w-8 object-contain" />
                </button>
                <button type="button" aria-label="设置" onClick={() => { settingsScrollPosition.current = 0; setDetailOrigin("settings"); setSettingsDetail(null); setSettingsOpen(true); }} className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current">
                  <img src={isDark ? settingsDarkIcon : settingsLightIcon} alt="" className="h-8 w-8 object-contain" />
                </button>
              </div>
            </>
          ) : (
            <>
          <button
            type="button"
            onClick={() => setIsDark((previous) => !previous)}
            aria-label={isDark ? "切换至浅色模式" : "切换至深色模式"}
            title={isDark ? "切换至浅色模式" : "切换至深色模式"}
            className={`flex h-11 w-11 cursor-pointer items-center justify-center rounded-full transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current ${isDark ? "active:bg-white/15" : "active:bg-black/10"}`}
          >
            <img src={isDark ? moonIcon : sunIcon} alt="" className="h-8 w-8 object-contain" />
          </button>
          <button type="button" aria-label="选择乐器课程" onClick={() => accountAction("课程")} className="absolute bottom-0 left-1/2 flex h-11 w-11 -translate-x-1/2 cursor-pointer items-center justify-center touch-manipulation transition-transform duration-75 active:translate-y-[2px] focus-visible:outline-2 focus-visible:outline-current motion-reduce:transition-none">
            <img src={selectedCourseImage} alt="" className="h-9 w-9 object-contain" />
          </button>
          <button
            type="button"
            onClick={openHistory}
            aria-label={`连续练琴 ${streak} 天，查看练习记录`}
            title="查看练习记录"
            className={`flex h-11 min-w-16 cursor-pointer items-center justify-center gap-1.5 rounded-full px-2 transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current ${streak > 0 ? isDark ? "text-[#d4d4d4]" : "text-[#666666]" : "text-[#8a8a8a]"} ${isDark ? "active:bg-white/15" : "active:bg-black/10"}`}
          >
            <StreakNote active={streak > 0} isDark={isDark} className="h-7 w-[25px] shrink-0" />
            <span aria-live="polite" className="text-[17px] font-medium tabular-nums">{streak}</span>
          </button>
            </>
          )}
        </header>
        <main ref={mainScroll} onScroll={(event) => { if (activeTab === "account") setAccountScrolled(event.currentTarget.scrollTop > 5); }} className={`min-h-0 flex-1 overscroll-contain [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${activeTab === "official" ? "overflow-hidden" : "overflow-y-auto"}`} aria-label={tabs.find((tab) => tab.id === activeTab)?.label}>
          {activeTab === "official" && <OfficialScoresPage isDark={isDark} />}
          {activeTab === "library" && <ConnectedScoresPage isDark={isDark} normalImage={scoresUploadNormal} pressedImage={scoresUploadPressed} />}
          {activeTab === "practice" && <ConnectedHistoryPage isDark={isDark} openCalendar={openHistory} />}
          {activeTab === "ai" && <MusicAssistantPage isDark={isDark} streak={streak} practiceCount={practice.count} />}
          {activeTab === "account" && <AccountPage isDark={isDark} streak={streak} practiceCount={practice.count} avatarSrc={customAvatar || selectedOutfitImage || (savedAvatar === "portrait" ? accountLightIcon : aiIcon)} courseImage={selectedCourseImage} onAction={accountAction} />}
        </main>
        <footer className={`z-20 shrink-0 pb-[env(safe-area-inset-bottom)] transition-colors duration-200 ${isDark ? "bg-[#141414]" : "bg-white"}`}>
          <nav aria-label="底部导航" className={`grid grid-cols-5 border-t px-3 pt-3 ${isDark ? "border-white/10" : "border-black/[0.08]"}`}>
            {tabs.map((tab) => (
              <button
                key={tab.id}
                type="button"
                aria-current={activeTab === tab.id ? "page" : undefined}
                onClick={() => tab.id === "account" && activeTab === "account" ? setAccountMenuOpen(true) : setActiveTab(tab.id)}
                className={`flex min-h-[62px] cursor-pointer flex-col items-center justify-start gap-[6px] rounded-lg pt-1 text-[11px] leading-4 tracking-[0.02em] transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-current ${activeTab === tab.id ? `font-medium ${isDark ? "text-white" : "text-black"}` : "font-normal text-[#8a8a8a]"}`}
              >
                <TabIcon kind={tab.id} isDark={isDark} />
                <span>{tab.label}</span>
              </button>
            ))}
          </nav>
        </footer>
        <dialog ref={accountMenu} aria-label="账号菜单" onCancel={() => setAccountMenuOpen(false)} onClose={() => setAccountMenuOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) setAccountMenuOpen(false); }} className={`fixed inset-x-0 top-auto bottom-[calc(75px+env(safe-area-inset-bottom))] mx-auto mb-0 w-full max-w-none sm:max-w-[680px] border-0 p-0 font-sans backdrop:bg-black/40 backdrop:[clip-path:inset(0_0_calc(76px_+_env(safe-area-inset-bottom))_0)] open:animate-account-menu motion-reduce:animate-none ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#4b4b4b]"}`}>
          <div>
            {[{ name: "个人档案", kind: "person" }, { name: "订购", kind: "bolt" }].map((item) => <button key={item.name} type="button" onClick={() => { setAccountMenuOpen(false); accountAction(item.name === "订购" ? "挑选套餐" : item.name); }} className={`flex min-h-[72px] w-full cursor-pointer items-center gap-5 border-b-2 px-6 text-[21px] font-bold focus-visible:outline-2 focus-visible:outline-current ${isDark ? "border-white/10" : "border-[#e5e5e5]"}`}><AccountSymbol kind={item.kind} className={`h-7 w-7 ${item.kind === "person" ? "text-[#29c6df]" : "text-[#7958ee]"}`} />{item.name}</button>)}
            <button type="button" aria-label="关闭账号菜单" onClick={() => setAccountMenuOpen(false)} className="absolute top-1 right-2 flex h-8 w-8 cursor-pointer items-center justify-center text-[20px] text-[#aaa]">×</button>
          </div>
        </dialog>
        <dialog ref={wardrobeDialog} aria-labelledby="wardrobe-title" onCancel={(event) => { event.preventDefault(); setWardrobeOpen(false); }} onClose={() => setWardrobeOpen(false)} className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-hidden border-0 p-0 font-sans backdrop:bg-black/40 backdrop:transition-colors backdrop:duration-[260ms] data-[closing=true]:backdrop:bg-black/0 motion-reduce:backdrop:transition-none open:animate-settings-sheet motion-reduce:animate-none ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#4b4b4b]"}`}>
          <div className="mx-auto flex h-full w-full max-w-none sm:max-w-[680px] flex-col">
            <div className={`shrink-0 pt-[var(--yinban-top-inset)] ${isDark ? "bg-[#292929]" : "bg-[#e7e7e7]"}`}>
              <header className="relative flex h-14 items-center justify-center">
                <button type="button" aria-label="关闭造型选择" onClick={() => setWardrobeOpen(false)} className={`absolute left-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-current ${isDark ? "active:bg-white/15" : "active:bg-black/10"}`}><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="m4 4 16 16M20 4 4 20" /></svg></button>
                <h1 id="wardrobe-title" className="max-w-[60%] truncate text-[20px] font-bold">{previewLocked ? previewOutfit.label : "选择你的造型"}</h1>
                <button type="button" disabled={previewLocked || (draftAvatar === savedAvatar && previewOutfitId === savedOutfit && !customAvatar)} onClick={() => { setSavedAvatar(draftAvatar); const outfit = wardrobeTab === "outfits" ? previewOutfitId : "plain"; setSavedOutfit(outfit); localStorage.setItem("music-outfit", outfit); localStorage.removeItem("music-profile-avatar"); setCustomAvatar(null); setWardrobeOpen(false); }} className={`absolute right-3 h-9 min-w-12 cursor-pointer rounded-[10px] border-b-[5px] border-[#ddd] bg-white px-2.5 text-[15px] font-bold text-[#4b4b4b] focus-visible:outline-2 focus-visible:outline-current disabled:cursor-default disabled:text-[#aaa] ${pressFeedback}`}>保存</button>
              </header>
              <div className="relative flex h-[clamp(160px,32dvh,290px)] items-end justify-center overflow-hidden px-5 pt-4">
                <img src={wardrobeTab === "outfits" && previewOutfit.id !== "plain" ? previewOutfit.image : draftAvatarImage} alt={previewLocked ? `${previewOutfit.label}装扮预览，尚未解锁` : "当前头像预览"} className="h-full max-w-[75%] object-contain" />
                {previewLocked && <button type="button" onClick={() => setShowOutfitProgress(true)} className={`absolute inset-x-4 bottom-3 h-11 cursor-pointer rounded-[14px] border-b-[5px] border-[#ddd] bg-white text-[17px] font-bold text-[#67db23] ${pressFeedback}`}>查看进度</button>}
              </div>
            </div>
            <div role="tablist" aria-label="造型分类" className={`grid shrink-0 grid-cols-2 border-b-2 ${isDark ? "border-white/10" : "border-[#e5e5e5]"}`}>
              {[{ id: "outfits", label: "装扮套装" }, { id: "avatars", label: "个人头像" }].map((tab) => <button key={tab.id} id={`wardrobe-tab-${tab.id}`} role="tab" aria-selected={wardrobeTab === tab.id} aria-controls="wardrobe-panel" type="button" onClick={() => { setWardrobeTab(tab.id); setWardrobeMessage(""); setShowOutfitProgress(false); if (tab.id === "avatars") setPreviewOutfitId("plain"); }} className={`relative h-14 cursor-pointer text-[17px] font-bold focus-visible:outline-2 focus-visible:outline-current ${wardrobeTab === tab.id ? "text-[#67db23] after:absolute after:inset-x-0 after:-bottom-[2px] after:h-1 after:rounded-full after:bg-[#67db23]" : "text-[#aaa]"}`}>{tab.label}</button>)}
            </div>
            <div id="wardrobe-panel" role="tabpanel" aria-labelledby={`wardrobe-tab-${wardrobeTab}`} className="min-h-0 flex-1 overflow-y-auto px-4 pt-5 pb-[max(28px,env(safe-area-inset-bottom))] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
              <div className="grid grid-cols-3 gap-x-3 gap-y-5">
                {wardrobeTab === "outfits" ? wardrobeOutfits.map((outfit) => <div key={outfit.id}>
                  <button type="button" aria-label={`${outfit.label}${outfit.practiceExclusive ? "，练琴专属" : ""}${outfitUnlocked(outfit.id) ? "，已解锁" : "，尚未解锁，可预览"}`} aria-pressed={previewOutfitId === outfit.id} onClick={() => { setPreviewOutfitId(outfit.id); setShowOutfitProgress(false); setWardrobeMessage(""); }} className={`relative flex aspect-[0.8] w-full cursor-pointer flex-col overflow-visible rounded-[20px] border-2 border-b-[5px] focus-visible:outline-2 focus-visible:outline-current ${pressFeedback} ${previewOutfitId === outfit.id ? "border-[#a0eb76] bg-[#effbe7]" : outfit.practiceExclusive ? "border-[#e0d5f0]" : isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
                    {outfit.practiceExclusive && <span className="absolute -top-3 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded-md bg-[#b395d5] px-2 py-0.5 text-[12px] font-bold text-white">练琴专属</span>}
                    <div className="min-h-0 flex-1 overflow-hidden rounded-t-[17px] px-1 pt-2"><img src={outfit.id === "plain" ? draftAvatarImage : outfit.image} alt="" loading="lazy" decoding="async" className="h-full w-full object-contain" /></div>
                    {outfit.id !== "plain" && <div className={`flex h-7 shrink-0 items-center justify-center rounded-b-[15px] ${previewOutfitId === outfit.id ? "bg-[#d3f5bd] text-[#67db23]" : outfit.practiceExclusive ? "bg-[#f0eaf8] text-[#ac91cf]" : isDark ? "bg-white/5 text-[#aaa]" : "bg-[#f7f7f7] text-[#aaa]"}`}><AccountSymbol kind={outfitUnlocked(outfit.id) ? "music" : "lock"} className="h-4 w-4" /></div>}
                  </button><p className={`mt-2 text-center text-[15px] font-bold leading-5 ${previewOutfitId === outfit.id ? "text-[#67db23]" : "text-[#aaa]"}`}>{outfit.label}</p>
                </div>) : [{ id: "mascot", label: "黑白键小猫3D", image: aiIcon }, { id: "portrait", label: "黑白键小猫2D", image: accountLightIcon }].map((avatar) => <div key={avatar.id}><button type="button" aria-label={avatar.label} aria-pressed={draftAvatar === avatar.id} onClick={() => { setDraftAvatar(avatar.id); setPreviewOutfitId("plain"); setShowOutfitProgress(false); setWardrobeMessage(""); }} className={`flex aspect-[0.8] w-full cursor-pointer items-center justify-center rounded-[20px] border-2 border-b-[5px] p-2 focus-visible:outline-2 focus-visible:outline-current ${pressFeedback} ${draftAvatar === avatar.id ? "border-[#a0eb76] bg-[#effbe7]" : isDark ? "border-white/15" : "border-[#e5e5e5]"}`}><img src={avatar.image} alt="" className="h-full w-full object-contain" /></button><p className={`mt-2 text-center text-[15px] font-bold ${draftAvatar === avatar.id ? "text-[#67db23]" : "text-[#aaa]"}`}>{avatar.label}</p></div>)}
              </div>
              <p role="status" className="mt-4 text-[12px] leading-6 text-[#999]">{wardrobeMessage}</p>
            </div>
          </div>
        </dialog>
        <dialog ref={outfitProgressDialog} aria-labelledby="outfit-progress-title" onCancel={(event) => { event.preventDefault(); setShowOutfitProgress(false); }} onClose={() => setShowOutfitProgress(false)} className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto border-0 p-0 font-sans [scrollbar-width:none] [&::-webkit-scrollbar]:hidden backdrop:bg-black/40 backdrop:transition-colors backdrop:duration-[260ms] data-[closing=true]:backdrop:bg-black/0 motion-reduce:backdrop:transition-none open:animate-settings-sheet motion-reduce:animate-none ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#4b4b4b]"}`}>
          {showOutfitProgress && <OutfitProgress isDark={isDark} selectedId={previewOutfitId} onBack={() => setShowOutfitProgress(false)} onPractice={() => { setShowOutfitProgress(false); setWardrobeOpen(false); setActiveTab("library"); }} onPreview={(id) => { setPreviewOutfitId(id); setShowOutfitProgress(false); }} />}
        </dialog>
        <dialog
          ref={historyDialog}
          aria-labelledby="history-title"
          onCancel={(event) => { event.preventDefault(); setHistoryOpen(false); }}
          onClose={() => setHistoryOpen(false)}
          className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto rounded-none border-0 p-0 font-sans [scrollbar-width:none] [&::-webkit-scrollbar]:hidden backdrop:bg-black/40 backdrop:transition-colors backdrop:duration-[260ms] data-[closing=true]:backdrop:bg-black/0 motion-reduce:backdrop:transition-none open:animate-history-sheet motion-reduce:animate-none ${isDark ? "bg-[#191919] text-white" : "bg-white text-[#29292f]"}`}
        >
          <div className="mx-auto flex h-dvh min-h-[650px] w-full max-w-none sm:max-w-[680px] flex-col pb-[max(16px,env(safe-area-inset-bottom))]">
            <div className="shrink-0 bg-[#b1f285] pt-[var(--yinban-top-inset)] text-[#25351e]">
            <header className="relative flex h-12 items-center justify-center">
              <button type="button" aria-label="关闭练习记录" onClick={() => setHistoryOpen(false)} className="absolute left-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full active:bg-black/10 focus-visible:outline-2 focus-visible:outline-current">
                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" aria-hidden="true"><path d="m4 4 16 16M20 4 4 20" /></svg>
              </button>
              <h1 id="history-title" className="text-[20px] font-bold">连胜</h1>
            </header>
            <div className="relative mt-1 flex h-10 items-center justify-center border-b-[3px] border-[#8acb62] text-[17px] font-bold text-[#25351e] after:absolute after:inset-x-0 after:-bottom-[3px] after:h-[4px] after:rounded-full after:bg-[#8acb62]">个人连胜</div>
            <div className="px-5 py-3">
              <section aria-label={`${historyStreak}天连胜啦！`} className="flex h-[clamp(90px,15dvh,130px)] items-center justify-between gap-3">
                <div className="flex flex-col items-start">
                  {historyStreak === 0 ? <svg role="img" aria-label="0" viewBox="0 0 110 160" className="h-[clamp(60px,9dvh,86px)] w-auto">
                    <ellipse cx="55" cy="80" rx="49" ry="76" fill="#b3e38d" />
                    <ellipse cx="55" cy="80" rx="32" ry="58" fill="white" />
                    <ellipse cx="55" cy="80" rx="14" ry="38" fill="#b3e38d" />
                  </svg> : <span className="inline-grid text-[clamp(60px,9dvh,86px)] font-extrabold leading-none tabular-nums">
                    <span aria-hidden="true" className="[grid-area:1/1] text-[#b3e38d] [-webkit-text-stroke:10px_#b3e38d]">{historyStreak}</span>
                    <span aria-hidden="true" className="[grid-area:1/1] text-white [-webkit-text-stroke:5px_white]">{historyStreak}</span>
                    <span className="[grid-area:1/1] text-[#b3e38d]">{historyStreak}</span>
                  </span>}
                  <span className="mt-1 pl-5 text-[20px] font-bold leading-7 text-[#25351e]">天连胜啦！</span>
                </div>
                <StreakNote active={historyStreak > 0} isDark={isDark} className="mr-3 h-full w-[110px] shrink-0" />
              </section>
            </div>
            </div>
            <div className="flex min-h-0 flex-1 flex-col px-4 pt-3">
              <div className="mb-3 flex shrink-0 items-center justify-between">
                <h2 aria-live="polite" className="text-[24px] font-bold tabular-nums">{year}年{month + 1}月</h2>
                <div className="flex gap-2 text-[#aaaaaa]">
                  {[-1, 1].map((direction) => (
                    <button key={direction} type="button" aria-label={direction === -1 ? "前一个月" : "后一个月"} onClick={() => changeMonth(direction)} className="flex h-11 w-11 cursor-pointer items-center justify-center rounded-xl focus-visible:outline-2 focus-visible:outline-current">
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={direction === -1 ? "m15 5-7 7 7 7" : "m9 5 7 7-7 7"} /></svg>
                    </button>
                  ))}
                </div>
              </div>
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden touch-pan-y" onTouchStart={(event) => {
                monthTouch.current = { x: event.touches[0].clientX, y: event.touches[0].clientY };
              }} onTouchEnd={(event) => {
                const start = monthTouch.current;
                monthTouch.current = null;
                if (!start) return;
                const horizontal = event.changedTouches[0].clientX - start.x;
                const vertical = event.changedTouches[0].clientY - start.y;
                if (Math.abs(horizontal) > 50 && Math.abs(horizontal) > Math.abs(vertical)) changeMonth(horizontal > 0 ? -1 : 1);
              }} onTouchCancel={() => { monthTouch.current = null; }}>
              <div key={`${year}-${month}`} className={`flex min-h-0 flex-1 flex-col motion-reduce:animate-none ${monthDirection === 1 ? "animate-month-next" : monthDirection === -1 ? "animate-month-previous" : ""}`}>
              <div className="grid shrink-0 grid-cols-2 gap-3">
              <div className={`flex items-start gap-2 rounded-[20px] border-2 px-3 py-3 ${isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="mt-1 shrink-0"><circle cx="12" cy="12" r="12" fill="#67db23" /><path d="m7 12 3 3 7-7" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" /></svg>
                <div><span className="text-[22px] font-bold leading-7 tabular-nums">{monthlyPracticeDays}</span><p className="text-[15px] text-[#aaaaaa]">打卡天数</p></div>
              </div>
              <div className={`flex items-start gap-2 rounded-[20px] border-2 px-3 py-3 ${isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="mt-1 shrink-0"><circle cx="12" cy="12" r="12" fill="#adadb7" /><path d="M7 12h10" stroke="white" strokeWidth="2.5" strokeLinecap="round" /></svg>
                <div><span className="text-[22px] font-bold leading-7 tabular-nums">{missedPracticeDays}</span><p className="whitespace-nowrap text-[15px] text-[#aaaaaa]">未打卡天数</p></div>
              </div>
              </div>
              <section aria-label={`${year}年${month + 1}月练琴日历`} className={`mt-3 flex min-h-0 flex-1 flex-col rounded-[20px] border-2 px-3 py-3 ${isDark ? "border-white/15" : "border-[#e5e5e5]"}`}>
                <div className="grid grid-cols-7 text-center text-[16px] font-medium text-[#aaaaaa]">
                  {["日", "一", "二", "三", "四", "五", "六"].map((weekday) => <div key={weekday} className="py-2">{weekday}</div>)}
                </div>
                <div className="mt-1 grid min-h-0 flex-1 auto-rows-fr grid-cols-7">
                  {Array.from({ length: firstWeekday }, (_, index) => <div key={`empty-${index}`} />)}
                  {Array.from({ length: monthDays }, (_, index) => {
                    const day = index + 1;
                    const dayNumber = Date.UTC(year, month, day) / 86400000;
                    const practiced = stats.days.has(dayNumber);
                    const isToday = dayNumber === today;
                    return (
                      <div key={day} aria-label={`${month + 1}月${day}日${isToday ? "，今天" : ""}，${practiced ? "已练琴" : "无练琴记录"}`} aria-current={isToday ? "date" : undefined} className="flex min-h-0 items-center justify-center">
                        <div className={`relative flex aspect-square h-full max-h-9 w-auto max-w-9 items-center justify-center rounded-full text-[15px] font-bold tabular-nums ${practiced ? "bg-[#67db23] text-white" : isToday ? `${isDark ? "bg-white/15" : "bg-[#e9e9e9]"} text-[#aaaaaa]` : "text-[#aaaaaa]"}`}>{day}</div>
                      </div>
                    );
                  })}
                </div>
              </section>
              </div>
              </div>
            </div>
          </div>
        </dialog>
        <dialog
          ref={settingsDialog}
          aria-labelledby="settings-title"
          onCancel={(event) => { event.preventDefault(); setSettingsOpen(false); }}
          onClose={() => setSettingsOpen(false)}
          className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none overflow-y-auto border-0 p-0 font-sans [scrollbar-width:none] [&::-webkit-scrollbar]:hidden backdrop:bg-black/40 backdrop:transition-colors backdrop:duration-[260ms] data-[closing=true]:backdrop:bg-black/0 motion-reduce:backdrop:transition-none open:animate-settings-sheet motion-reduce:animate-none ${isDark ? "bg-[#191919] text-[#ededed]" : "bg-white text-[#4b4b4b]"}`}
        >
          <div className={`mx-auto w-full max-w-none sm:max-w-[680px] ${settingsDetail === "课程" ? "flex h-dvh flex-col overflow-hidden" : "min-h-dvh pb-[max(28px,env(safe-area-inset-bottom))]"}`}>
            <header className={`sticky top-0 z-10 border-b-2 pt-[var(--yinban-top-inset)] ${isDark ? "border-white/10 bg-[#191919]" : "border-[#e5e5e5] bg-white"}`}>
              <div className="relative flex h-14 items-center justify-center">
                <button type="button" aria-label={settingsDetail ? detailOrigin === "account" ? "返回账号" : "返回设置" : "关闭设置"} onClick={() => settingsDetail && detailOrigin === "settings" ? setSettingsDetail(null) : setSettingsOpen(false)} className={`absolute left-3 flex h-11 w-11 cursor-pointer items-center justify-center rounded-full focus-visible:outline-2 focus-visible:outline-current ${isDark ? "active:bg-white/15" : "active:bg-black/10"}`}>
                  <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={settingsDetail && settingsDetail !== "课程" ? "m15 4-8 8 8 8" : "m4 4 16 16M20 4 4 20"} /></svg>
                </button>
                <h1 id="settings-title" className="max-w-[75%] truncate text-[20px] font-bold">{settingsDetail || "设置"}</h1>
              </div>
            </header>
            {settingsDetail === "课程" ? <CoursesPage isDark={isDark} selectedCourse={selectedCourse} onCourseChange={setSelectedCourse} onContinue={() => setSettingsOpen(false)} /> : settingsDetail ? (
              <SettingsContent key={settingsDetail} title={settingsDetail} isDark={isDark} toggleTheme={() => setIsDark((previous) => !previous)} name={displayName} onNameChange={setDisplayName} />
            ) : (
              <div className="px-4">
                {[
                  { label: "账户", items: ["偏好设置", "个人档案", "云端识谱", "通知", "课程", "黑白键课堂", "隐私设置"] },
                  { label: "订购", items: ["挑选套餐"] },
                  { label: "客服", items: ["客服中心", "反馈"] },
                ].map((group) => (
                  <section key={group.label} className={`border-b-2 py-7 ${isDark ? "border-white/10" : "border-[#e5e5e5]"}`}>
                    <h2 className="mb-4 text-[15px] font-medium text-[#aaa]">{group.label}</h2>
                    {group.items.map((item) => (
                      <button key={item} type="button" onClick={() => openSettingsDetail(item)} className="flex min-h-[60px] w-full cursor-pointer items-center justify-between gap-4 text-left text-[20px] font-bold focus-visible:outline-2 focus-visible:outline-current">
                        <span>{item}</span>
                        <svg width="20" height="22" viewBox="0 0 24 24" fill="none" stroke="#b5b5b5" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m9 4 8 8-8 8" /></svg>
                      </button>
                    ))}
                    {(group.label === "订购" || group.label === "客服") && <button type="button" onClick={() => openSettingsDetail(group.label === "订购" ? "恢复订购" : "本机档案")} className={`mt-3 h-12 w-full cursor-pointer rounded-[14px] border-2 border-b-[5px] text-[17px] font-bold text-[#67db23] focus-visible:outline-2 focus-visible:outline-current ${isDark ? "border-white/15" : "border-[#e5e5e5]"} ${pressFeedback}`}>{group.label === "订购" ? "恢复订购" : "本机档案"}</button>}
                  </section>
                ))}
                <div className="flex flex-col items-start gap-6 py-7">
                  {["条款", "隐私政策", "致谢"].map((item) => <button key={item} type="button" onClick={() => openSettingsDetail(item)} className="cursor-pointer text-[16px] font-bold text-[#67db23] focus-visible:outline-2 focus-visible:outline-current">{item}</button>)}
                </div>
              </div>
            )}
          </div>
        </dialog>
      </div>
    </div>
  );
}
