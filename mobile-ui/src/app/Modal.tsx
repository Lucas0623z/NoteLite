import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Native dialogs contain keyboard focus and make the background inert for assistive technology. */
export default function Modal({ label, onDismiss, children, className = "", alert = false }: { label: string; onDismiss: () => void; children: ReactNode; className?: string; alert?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  // Capture before the commit: a child's autoFocus can run before this layout effect.
  const opener = useRef(document.activeElement instanceof HTMLElement ? document.activeElement : null);
  useLayoutEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => { if (dialog?.open) dialog.close(); if (opener.current?.isConnected) opener.current.focus(); };
  }, []);
  return <dialog ref={ref} role={alert ? "alertdialog" : "dialog"} aria-label={label} aria-modal="true" onCancel={event => { event.preventDefault(); onDismiss(); }} className={`fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none border-0 p-0 backdrop:bg-black/45 ${className}`}>
    {children}
  </dialog>;
}
