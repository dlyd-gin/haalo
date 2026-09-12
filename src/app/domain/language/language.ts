export interface Language {
  readonly code: string;
  readonly label: string;
  readonly flag: string; // emoji, used at small sizes (e.g. the picker options)
  readonly flagCountryCode: string; // ISO 3166-1 alpha-2, resolves the /flags/<code>.svg asset
}
