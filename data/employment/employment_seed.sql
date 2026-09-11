-- Demo schema and data for the public-employment search pilot.

PRAGMA foreign_keys = ON;

CREATE TABLE organizations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    ministry TEXT NOT NULL
);

CREATE TABLE locations (
    id INTEGER PRIMARY KEY,
    region TEXT NOT NULL,
    city TEXT NOT NULL
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    organization_id INTEGER NOT NULL REFERENCES organizations(id),
    location_id INTEGER NOT NULL REFERENCES locations(id),
    contract_type TEXT NOT NULL,
    employment_type TEXT NOT NULL,
    education_level TEXT NOT NULL,
    grade TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    publication_date TEXT NOT NULL,
    deadline TEXT NOT NULL,
    remote INTEGER NOT NULL CHECK (remote IN (0, 1)),
    status TEXT NOT NULL
);

CREATE TABLE job_skills (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);

CREATE INDEX idx_jobs_publication_date ON jobs(publication_date);
CREATE INDEX idx_jobs_deadline ON jobs(deadline);
CREATE INDEX idx_jobs_organization ON jobs(organization_id);
CREATE INDEX idx_jobs_location ON jobs(location_id);
CREATE INDEX idx_job_skills_skill ON job_skills(skill);

INSERT INTO organizations (id, name, ministry) VALUES
    (1, 'Agence Nationale du Digital', 'Ministère de la Transition Numérique'),
    (2, 'Centre Hospitalier Universitaire Ibn Sina', 'Ministère de la Santé et de la Protection Sociale'),
    (3, 'Université Mohammed V de Rabat', 'Ministère de l''Enseignement Supérieur'),
    (4, 'Direction Générale des Impôts', 'Ministère de l''Économie et des Finances');

INSERT INTO locations (id, region, city) VALUES
    (1, 'Rabat-Salé-Kénitra', 'Rabat'),
    (2, 'Casablanca-Settat', 'Casablanca'),
    (3, 'Fès-Meknès', 'Fès'),
    (4, 'Marrakech-Safi', 'Marrakech');

INSERT INTO jobs (
    id, title, description, organization_id, location_id, contract_type,
    employment_type, education_level, grade, salary_min, salary_max,
    publication_date, deadline, remote, status
) VALUES
    ('emploi-001', 'Ingénieur logiciel et données',
     'Conception de services numériques publics, APIs et pipelines de données.',
     1, 1, 'Titulaire', 'Temps plein', 'Master', 'Grade 11', 12000, 18000,
     '2026-08-20', '2026-09-30', 1, 'Ouvert'),
    ('emploi-002', 'Administrateur systèmes et réseaux',
     'Exploitation des infrastructures, sécurité réseau et continuité de service.',
     1, 2, 'Contractuel', 'Temps plein', 'Licence', 'Grade 10', 9000, 14000,
     '2026-08-24', '2026-10-05', 0, 'Ouvert'),
    ('emploi-003', 'Infirmier en soins spécialisés',
     'Prise en charge des patients et coordination des équipes de soins.',
     2, 1, 'Titulaire', 'Temps plein', 'Licence professionnelle', 'Grade 9', 8000, 12000,
     '2026-08-18', '2026-09-25', 0, 'Ouvert'),
    ('emploi-004', 'Chargé de la commande publique',
     'Préparation des marchés publics, suivi contractuel et analyse juridique.',
     4, 2, 'Contractuel', 'Temps plein', 'Master', 'Grade 11', 10000, 16000,
     '2026-07-30', '2026-09-15', 1, 'Ouvert'),
    ('emploi-005', 'Technicien de laboratoire',
     'Analyses biologiques, gestion des équipements et traçabilité des résultats.',
     2, 3, 'Titulaire', 'Temps plein', 'Technicien spécialisé', 'Grade 8', 6500, 9500,
     '2026-07-15', '2026-08-30', 0, 'Clôturé'),
    ('emploi-006', 'Maître de conférences en informatique',
     'Enseignement, recherche appliquée et encadrement des étudiants en informatique.',
     3, 1, 'Titulaire', 'Temps plein', 'Doctorat', 'Grade A', 15000, 22000,
     '2026-08-28', '2026-10-20', 1, 'Ouvert');

INSERT INTO job_skills (job_id, skill) VALUES
    ('emploi-001', 'Python'), ('emploi-001', 'SQL'), ('emploi-001', 'Cloud'),
    ('emploi-002', 'Linux'), ('emploi-002', 'Réseaux'), ('emploi-002', 'Cybersécurité'),
    ('emploi-003', 'Soins infirmiers'), ('emploi-003', 'Urgences'),
    ('emploi-004', 'Marchés publics'), ('emploi-004', 'Droit administratif'), ('emploi-004', 'Analyse'),
    ('emploi-005', 'Biologie'), ('emploi-005', 'Qualité'),
    ('emploi-006', 'Python'), ('emploi-006', 'Recherche'), ('emploi-006', 'Pédagogie');
