export const ROLE_OPTIONS = [
  "président",
  "coach",
  "trésorier",
  "secrétaire",
  "vice président",
  "co président",
  "manager sportif",
  "responsable",
  "aucune des catégories",
];
export const ROLE_DEFAULT = "aucune des catégories";

export const STATUT_OPTIONS = [
  "à contacter",
  "en cours",
  "rdv fixé",
  "proposition envoyée",
  "signé",
  "pas signé",
  "à relancer",
];
export const STATUT_DEFAULT = "à contacter";

export const DEFAULT_PROSPECTION_COLUMNS = [
  { id: "col_nom_club", name: "Nom du club", type: "text", width: 220, defaultValue: "", options: [] },
  { id: "col_region", name: "Région", type: "text", width: 150, defaultValue: "", options: [] },
  { id: "col_departement", name: "Département", type: "text", width: 130, defaultValue: "", options: [] },
  { id: "col_site", name: "Site du club", type: "text", width: 200, defaultValue: "", options: [] },
  { id: "col_nom", name: "Nom", type: "text", width: 150, defaultValue: "", options: [] },
  { id: "col_role", name: "Rôle", type: "dropdown", width: 170, defaultValue: ROLE_DEFAULT, options: ROLE_OPTIONS },
  { id: "col_telephone", name: "Téléphone", type: "text", width: 140, defaultValue: "", options: [] },
  { id: "col_mail", name: "Mail", type: "text", width: 220, defaultValue: "", options: [] },
  {
    id: "col_statut",
    name: "Statut de la prospection",
    type: "dropdown",
    width: 190,
    defaultValue: STATUT_DEFAULT,
    options: STATUT_OPTIONS,
  },
  { id: "col_date_premier_contact", name: "Date premier contact", type: "date", width: 150, defaultValue: "", options: [] },
  { id: "col_date_derniere_action", name: "Date dernière action", type: "date", width: 150, defaultValue: "", options: [] },
  { id: "col_commentaires", name: "Commentaires", type: "text", width: 260, defaultValue: "", options: [] },
];

export const LEGACY_COLUMN_MAP = {
  ids: {
    col_ligue: "col_region",
    col_cd: "col_departement",
  },
  names: {
    "nom club": "col_nom_club",
    "nom du club": "col_nom_club",
    club: "col_nom_club",
    ligue: "col_region",
    region: "col_region",
    "région": "col_region",
    cd: "col_departement",
    departement: "col_departement",
    "département": "col_departement",
    site: "col_site",
    "site du club": "col_site",
    role: "col_role",
    "rôle": "col_role",
    statut: "col_statut",
    "statut de la prospection": "col_statut",
    telephone: "col_telephone",
    "téléphone": "col_telephone",
    mail: "col_mail",
    email: "col_mail",
    "e-mail": "col_mail",
    commentaires: "col_commentaires",
    commentaire: "col_commentaires",
    "date premier contact": "col_date_premier_contact",
    "date dernière action": "col_date_derniere_action",
    "date derniere action": "col_date_derniere_action",
  },
};

export function normalizeColumnKey(value) {
  if (value === null || value === undefined) {
    return "";
  }
  return String(value).trim().toLowerCase().normalize("NFC");
}
