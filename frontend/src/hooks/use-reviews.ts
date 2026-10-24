import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { useRuntimeEnvironment } from "@/hooks/use-runtime-environment"
import { useSession } from "@/hooks/use-session"
import {
  captureLocalSourceSnapshot,
  localSourceIdentityHash,
} from "@/lib/local-source-snapshot"
import { getLocalProjectsDatabase } from "@/lib/local-projects-database"
import {
  projectsApi,
  reviewsApi,
  type Project,
  type Review,
} from "@/lib/api"

export type { Review }

export const reviewsQueryKey = ["reviews"] as const
const PROJECT_REVIEWS_PAGE_SIZE = 10

export function useProjectReviews(projectId: string | null, page: number) {
  return useQuery({
    queryKey: [...reviewsQueryKey, "project", projectId, page],
    queryFn: () =>
      reviewsApi.list({
        projectId: projectId!,
        page,
        pageSize: PROJECT_REVIEWS_PAGE_SIZE,
      }),
    enabled: projectId !== null,
    refetchInterval: (query) =>
      query.state.data?.items.some(
        (review) => review.status === "queued" || review.status === "running",
      )
        ? 5000
        : false,
    retry: false,
  })
}

type CreateReviewInput = {
  project: Project
  agentIds: string[]
}

async function provisionLocalProject(
  project: Project,
  accountId: string,
): Promise<{ projectId: string; canonicalPath: string; sourceId: string }> {
  if (!project.local_source_id) {
    throw new Error("The local project source is unavailable.")
  }

  const database = await getLocalProjectsDatabase()
  const desktopProject = await database.get(accountId, project.id)
  if (!desktopProject || desktopProject.source.kind !== "local") {
    throw new Error("The local project source is unavailable.")
  }

  if (desktopProject.source.availability !== "available") {
    throw new Error("Reconnect the local folder before starting a review.")
  }

  if (desktopProject.source.apiProjectId) {
    return {
      projectId: desktopProject.source.apiProjectId,
      canonicalPath: desktopProject.source.canonicalPath,
      sourceId: desktopProject.source.sourceId,
    }
  }

  const created = await projectsApi.create({
    name: project.name,
    source: "local",
    local_path_hash: await localSourceIdentityHash(desktopProject.source.sourceId),
    category: project.category,
    auto_create_pull_requests: false,
  })
  const updatedAt = new Date().toISOString()

  await database.updateLocal({
    ...desktopProject,
    source: {
      ...desktopProject.source,
      apiProjectId: created.id,
    },
    updatedAt,
  })

  return {
    projectId: created.id,
    canonicalPath: desktopProject.source.canonicalPath,
    sourceId: desktopProject.source.sourceId,
  }
}

export function useCreateReview() {
  const queryClient = useQueryClient()
  const runtime = useRuntimeEnvironment()
  const session = useSession()

  return useMutation({
    mutationFn: async ({ project, agentIds }: CreateReviewInput) => {
      if (project.source === "local") {
        if (!runtime.isTauri) {
          throw new Error("Local source reviews are available in the desktop app only.")
        }

        const accountId = session.data?.user_id
        if (!accountId) {
          throw new Error("Sign in before starting a review.")
        }

        const localProject = await provisionLocalProject(project, accountId)
        const snapshot = await captureLocalSourceSnapshot(
          localProject.canonicalPath,
        )

        return reviewsApi.create(
          {
            project_id: localProject.projectId,
            agent_ids: agentIds,
            local_source_snapshot: {
              source_id: localProject.sourceId,
              integrity_algorithm: snapshot.integrityAlgorithm,
              digest: snapshot.digest,
            },
          },
          crypto.randomUUID(),
        )
      }

      return reviewsApi.create(
        {
          project_id: project.api_project_id ?? project.id,
          agent_ids: agentIds,
        },
        crypto.randomUUID(),
      )
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: reviewsQueryKey })
    },
  })
}

export function useReview(reviewId: string | undefined) {
  return useQuery({
    queryKey: [...reviewsQueryKey, reviewId],
    queryFn: () => reviewsApi.get(reviewId!),
    enabled: Boolean(reviewId),
    refetchInterval: (query) =>
      query.state.data?.status === "queued" ||
      query.state.data?.status === "running"
        ? 5000
        : false,
    retry: false,
  })
}
