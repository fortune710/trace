export const findingFilterParameterNames = {
  category: "finding_category",
  severity: "finding_severity",
  status: "finding_status",
  agentId: "finding_agent",
} as const

export const findingPageParameterName = "finding_page"

export function clearFindingSearchParams(searchParams: URLSearchParams) {
  const nextSearchParams = new URLSearchParams(searchParams)

  for (const parameterName of [
    ...Object.values(findingFilterParameterNames),
    findingPageParameterName,
  ]) {
    nextSearchParams.delete(parameterName)
  }

  return nextSearchParams
}
