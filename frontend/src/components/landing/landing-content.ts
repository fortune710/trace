export const REPOSITORY_URL = "https://github.com/fortune710/trace"

export const navLinks = [
  { label: "Features", href: "#features" },
  { label: "How it works", href: "#how-it-works" },
  { label: "Platforms", href: "#platforms" },
  { label: "FAQ", href: "#faq" },
] as const

export const reviewCategories = [
  "Security",
  "Engineering",
  "Product",
  "Legal",
  "Accessibility",
  "Marketing",
] as const

export type Feature = {
  title: string
  description: string
  wide?: boolean
}

export const features: Feature[] = [
  {
    title: "Review from every angle",
    description:
      "Each reviewer owns one lens, so a security pass never gets diluted by a copy edit. Pick the reviewers for each run and Trace reads your project through all of them.",
    wide: true,
  },
  {
    title: "Findings that show their work",
    description:
      "Every finding carries a severity, the affected file, the evidence behind it and a recommendation written in plain language.",
  },
  {
    title: "Triage without the noise",
    description:
      "Filter by category, severity or status. Accept what matters, dismiss what does not, and mark things resolved as you ship.",
  },
  {
    title: "Proposed diffs",
    description:
      "When a reviewer recommends a change, Trace shows the explanation, the affected files and the exact diff before anything is produced.",
  },
  {
    title: "Reviewers you configure",
    description:
      "Start with Harvey Specter, Mark Zuckerberg and Super PM, or create your own with a name, personality, category and model.",
  },
  {
    title: "Hand findings to your tracker",
    description:
      "Open a GitHub or Linear issue straight from a finding, or copy a ready-made prompt for your coding agent.",
  },
  {
    title: "Pinned to your source",
    description:
      "Every review records the commit it read, or a snapshot of your local folder, so a finding always points at the code you reviewed.",
  },
  {
    title: "Your keys stay yours",
    description:
      "Use Trace-managed model access, or bring your own OpenAI, Anthropic, Google or xAI key. Saved keys are encrypted and never shown again.",
  },
]

export const approvalPoints = [
  {
    title: "Review",
    description:
      "Reviewers report findings and propose a change. Nothing is written yet.",
  },
  {
    title: "Accept",
    description:
      "You read the explanation and the diff, then accept the finding. Until you do, the action buttons stay disabled.",
  },
  {
    title: "Apply",
    description:
      "On GitHub projects Trace opens a pull request. On the macOS app it backs up each file, then applies the change to your folder.",
  },
] as const

export const steps = [
  {
    title: "Connect your project",
    description:
      "Import a GitHub repository and branch on the web, or pick a local folder in the macOS app. Choose a project category so reviewers know what you are building.",
  },
  {
    title: "Choose your reviewers",
    description:
      "Select the reviewers for this run and start the review. Trace does not share your project with a model provider until you do.",
  },
  {
    title: "Triage and fix",
    description:
      "Work through findings, accept the ones you agree with, and send the fixes out as pull requests, local changes or issues.",
  },
] as const

export const platforms = [
  {
    name: "Web",
    description:
      "Import a GitHub repository, review it in the browser and turn accepted findings into pull requests.",
    points: [
      "Sign in with GitHub, Google or email",
      "Choose a repository and branch",
      "Pull requests created after you approve",
    ],
  },
  {
    name: "macOS app",
    description:
      "Review a project that lives on your machine. Trace reads only the folder you select.",
    points: [
      "Pick any local project folder",
      "Backups saved before a change is applied",
      "Your local path stays on your device",
    ],
  },
] as const

export const faqs = [
  {
    question: "Will Trace change my code on its own?",
    answer:
      "No. Trace proposes changes and shows you the diff. A pull request is created or a local file is changed only after you accept the finding and confirm the action.",
  },
  {
    question: "Where does my source code go?",
    answer:
      "A model provider receives your project only after you start a review, and only the provider you chose for that reviewer. Choose Trace-managed access or bring your own key.",
  },
  {
    question: "Are the Legal findings legal advice?",
    answer:
      "No. Legal findings are informational guidance. Talk to qualified counsel before you make legal decisions.",
  },
  {
    question: "Can my team use it?",
    answer:
      "Trace serves one person per account today. Team workspaces are not part of the first release.",
  },
  {
    question: "Which platforms does it run on?",
    answer:
      "The web app works in current browsers and imports from GitHub. The desktop app is built for macOS 10.15 or later and reviews local folders.",
  },
] as const
