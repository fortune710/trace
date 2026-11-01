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

export type BentoFeature = {
  id: "review-angles" | "evidence" | "reviewers" | "handoff"
  title: string
  description: string
  className: string
}

export const bentoFeatures: BentoFeature[] = [
  {
    id: "review-angles",
    title: "Review from every angle",
    description:
      "Each reviewer owns one lens, so a security pass never gets diluted by a copy edit. Pick the reviewers for each run and Trace reads your project through all of them.",
    className: "lg:col-span-3",
  },
  {
    id: "evidence",
    title: "Findings that show their work",
    description:
      "Every finding carries a severity, the affected file, the evidence behind it and a recommendation written in plain language.",
    className: "lg:col-span-3",
  },
  {
    id: "reviewers",
    title: "Reviewers you configure",
    description:
      "Start with Harvey Specter, Mark Zuckerberg and Super PM, or create your own with a name, personality, category and model. Use Trace-managed access or bring your own key.",
    className: "lg:col-span-4",
  },
  {
    id: "handoff",
    title: "Open a pull request or file an issue",
    description:
      "Accept a finding, then open a pull request straight from its proposed diff on GitHub projects, or hand it to GitHub or Linear as an issue.",
    className: "lg:col-span-2",
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
