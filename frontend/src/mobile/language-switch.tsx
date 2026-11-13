/**
 * Svenska | English: the app's language, chosen on the phone (app-language.ts). Each language is named in itself, so
 * whoever cannot read the current one still finds their own. Two buttons in one group, the chosen one pressed; each is
 * a 48 target. Drawn in Inställningar and, smaller in look but not in target, at the top of the pairing screen.
 */
import type { AppLocale } from "@/features/mcp-apps/app-locale";
import "./language-switch.css";

const NAMES: Record<AppLocale, string> = { sv: "Svenska", en: "English" };

export function LanguageSwitch({
  locale,
  onChange,
  label,
  compact = false,
}: {
  locale: AppLocale;
  onChange: (next: AppLocale) => void;
  /** The group's name for assistive technology (the `language` label). */
  label: string;
  /** The pairing screen's quiet form: text buttons at the end of the line, no frame. */
  compact?: boolean;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className={
        compact ? "mobile-language mobile-language--compact" : "mobile-language"
      }
    >
      {(["sv", "en"] as const).map((option) => (
        <button
          key={option}
          type="button"
          lang={option}
          className="sk-chip mobile-language__option"
          aria-pressed={option === locale}
          onClick={() => {
            if (option !== locale) onChange(option);
          }}
        >
          {NAMES[option]}
        </button>
      ))}
    </div>
  );
}
