import { Language } from './language';

export function orderLanguagesBySelected(
  languages: readonly Language[],
  selectedCode: string,
): Language[] {
  const selected = languages.find((language) => language.code === selectedCode);
  const rest = languages.filter((language) => language.code !== selectedCode);
  return selected ? [selected, ...rest] : [...languages];
}
