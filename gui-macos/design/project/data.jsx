// data.jsx — fixture articles. Multi-lingual, varied lengths.
const COLLECTIONS = [
  { name: "All articles", icon: "tray", count: 1284, smart: false, system: true },
];
const SMART = [
  { name: "Untagged", icon: "tag", count: 312 },
  { name: "Recently added", icon: "inbox-down", count: 28 },
  { name: "Most cited", icon: "star", count: 50 },
];
const USER_COLS = [
  { name: "Membrane fouling", count: 47 },
  { name: "수질관리특론", count: 23 },
  { name: "Anaerobic digestion", count: 18 },
  { name: "Nitrification kinetics", count: 12 },
  { name: "Reviews & meta-analyses", count: 8 },
  { name: "To re-read", count: 5 },
  { name: "PhD lit review", count: 102 },
];

const ARTICLES = [
  {
    eid: "2-s2.0-1", isNew: true,
    title: "Long-term performance of submerged anaerobic membrane bioreactors treating municipal wastewater under temperate-to-warm seasonal variation",
    firstAuthor: "Smith, J.",
    authors: ["Smith, J.", "Liu, W.", "Pereira, A. M.", "Tanaka, R.", "García-Vélez, S."],
    journal: "Water Research",
    year: "2024",
    coverDate: "2024-09-12",
    cited: 17,
    doi: "10.1016/j.watres.2024.121456",
    abstract:
      "Submerged anaerobic membrane bioreactors (AnMBRs) offer a promising route to energy-positive municipal wastewater treatment, but long-term performance under realistic temperature regimes is not well characterised. Here we report a 22-month pilot operation of a 1.2 m³ submerged AnMBR fed with raw municipal wastewater, spanning influent temperatures from 9.4 °C to 27.8 °C. Steady-state COD removal was 88.6 ± 4.2 %, with methane yields tracking influent biodegradable COD and falling 38 % at the lowest temperature decile. Membrane fouling was dominated by extracellular polymeric substances during cool periods, with cake resistance contributing the bulk of total resistance, while soluble microbial products dominated during warm summer months. We propose a temperature-stratified control strategy in which permeate flux is throttled in proportion to a rolling EPS estimate inferred from soluble protein and carbohydrate concentrations.",
    keywords: "AnMBR; membrane fouling; municipal wastewater; temperature; EPS; methane yield",
    tags: ["fouling", "anmbr", "review-2024"],
    collections: ["Membrane fouling", "PhD lit review"],
    notes: "Compare to Lin et al. 2022 — they report different fouling regimes at the same flux. Relevant for ch. 3.",
    addedAt: "Added 2 days ago",
  },
  {
    eid: "2-s2.0-2",
    title: "Pinch analysis of integrated water-and-energy networks in dairy processing plants",
    firstAuthor: "Pereira, A. M.",
    journal: "Journal of Cleaner Production", year: "2023", cited: 4,
    tags: ["pinch", "industrial-water"],
    collections: ["PhD lit review"],
  },
  {
    eid: "2-s2.0-3",
    title: "한국 하수처리장에서의 미량오염물질 거동 분석: 사례연구",
    firstAuthor: "Kim, S.-H.",
    journal: "Korean Journal of Environmental Engineering", year: "2024", cited: 0,
    tags: ["micropollutants", "field-data"],
    collections: ["수질관리특론"],
    isNew: true,
  },
  {
    eid: "2-s2.0-4",
    title: "Machine-learning surrogate models for full-scale activated sludge plants: a critical review",
    firstAuthor: "García-Vélez, S.", journal: "Environmental Modelling & Software", year: "2024", cited: 31,
    tags: ["ml", "review"], collections: ["Reviews & meta-analyses", "PhD lit review"],
  },
  {
    eid: "2-s2.0-5",
    title: "Granular sludge stability under transient organic loading: a meta-analysis of 47 pilot studies",
    firstAuthor: "Liu, W.", journal: "Bioresource Technology", year: "2023", cited: 22,
    tags: ["granular-sludge", "review-2024"], collections: ["Reviews & meta-analyses"],
  },
  {
    eid: "2-s2.0-6",
    title: "Coupling anammox with mainstream nitritation: pilot-scale evidence from cold-climate plants",
    firstAuthor: "Tanaka, R.", journal: "Water Research", year: "2024", cited: 9,
    tags: ["anammox", "nitritation"], collections: ["Nitrification kinetics"],
  },
  {
    eid: "2-s2.0-7",
    title: "Reactor-scale CFD validation against acoustic Doppler velocimetry in an anaerobic digester",
    firstAuthor: "Schmidt, K.", journal: "Chemical Engineering Science", year: "2022", cited: 56,
    tags: ["cfd"], collections: ["Anaerobic digestion"],
  },
  {
    eid: "2-s2.0-8",
    title: "혐기성 막생물반응조 운전조건이 슬러지 생성률에 미치는 영향",
    firstAuthor: "Park, J.-Y.", journal: "Journal of Korean Society on Water Environment", year: "2023", cited: 2,
    tags: ["anmbr"], collections: ["수질관리특론", "Anaerobic digestion"],
  },
  {
    eid: "2-s2.0-9",
    title: "On the use of ATP-based viability proxies in mixed-culture biofilms",
    firstAuthor: "Okafor, C.", journal: "Biotechnology and Bioengineering", year: "2021", cited: 88,
    tags: ["biofilm", "atp"], collections: ["PhD lit review"],
  },
  {
    eid: "2-s2.0-10",
    title: "Reverse-electrodialysis-driven crystallization for resource recovery from saline wastewater streams",
    firstAuthor: "Almeida, R.", journal: "Desalination", year: "2024", cited: 6,
    tags: ["resource-recovery"], collections: ["To re-read"],
  },
];

window.SCOPUS_DATA = { COLLECTIONS, SMART, USER_COLS, ARTICLES };
