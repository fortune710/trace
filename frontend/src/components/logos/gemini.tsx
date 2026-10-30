import type { SVGProps } from "react"

export function GoogleGeminiIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      {...props}
      xmlns="http://www.w3.org/2000/svg"
      width="1em"
      height="1em"
      viewBox="0 0 256 256"
    >
      <title>google-gemini-icon</title>
      <defs>
        <linearGradient
          id="gemini-gradient"
          x1="48"
          x2="208"
          y1="48"
          y2="208"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#4893fc" />
          <stop offset="0.52" stopColor="#969dff" />
          <stop offset="1" stopColor="#bd99fe" />
        </linearGradient>
      </defs>
      <path
        fill="url(#gemini-gradient)"
        d="M128 0c2.72 0 5.092 1.86 5.756 4.5c7.136 28.382 21.444 54.68 41.344 74.58c19.9 19.9 46.2 34.208 74.582 41.346A5.94 5.94 0 0 1 256 128a5.94 5.94 0 0 1-6.318 7.576c-28.382 7.138-54.682 21.446-74.582 41.346c-19.9 19.9-34.208 46.198-41.344 74.58A5.94 5.94 0 0 1 128 256a5.94 5.94 0 0 1-5.756-4.5c-7.136-28.382-21.444-54.68-41.344-74.58C61 157.02 34.7 142.712 6.318 135.574A5.94 5.94 0 0 1 0 128a5.94 5.94 0 0 1 6.318-7.576C34.7 113.286 61 98.978 80.9 79.078C100.8 59.18 115.108 32.88 122.244 4.5A5.94 5.94 0 0 1 128 0Z"
      />
    </svg>
  )
}

export default GoogleGeminiIcon
