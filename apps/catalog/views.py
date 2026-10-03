from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.reverse import reverse

from apps.core.permissions import IsStaffOrReadOnly

from . import poster
from .models import Genre, Movie


class GenreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Genre
        fields = ["id", "slug", "name"]


class MovieSerializer(serializers.ModelSerializer):
    genres = serializers.SlugRelatedField(slug_field="slug", many=True, queryset=Genre.objects.all(), required=False)
    poster = serializers.SerializerMethodField()
    trailer_url = serializers.CharField(read_only=True)

    class Meta:
        model = Movie
        fields = [
            "id", "slug", "title", "status", "release_date", "runtime_minutes", "synopsis", "genres",
            "directors", "cast", "countries", "languages", "poster", "poster_url", "trailer_youtube_id",
            "trailer_url", "popularity", "source_url",
        ]
        extra_kwargs = {"poster_url": {"write_only": True}}

    def get_poster(self, movie):
        if movie.poster_url:
            return movie.poster_url
        return reverse("movie-poster", kwargs={"slug": movie.slug}, request=self.context.get("request"))


class MovieViewSet(viewsets.ModelViewSet):
    """Movies. Filters: `status`, `genre` (slug), `q` (title, cast or director)."""

    serializer_class = MovieSerializer
    permission_classes = [IsStaffOrReadOnly]
    lookup_field = "slug"

    def get_queryset(self):
        qs = Movie.objects.prefetch_related("genres")
        params = self.request.query_params
        if status := params.get("status"):
            qs = qs.filter(status=status)
        if genre := params.get("genre"):
            qs = qs.filter(genres__slug=genre)
        if q := params.get("q"):
            # JSON lists are searched as text, which works on SQLite and PostgreSQL alike
            qs = qs.filter(Q(title__icontains=q) | Q(cast__icontains=q) | Q(directors__icontains=q))
        if params.get("showing") == "upcoming":
            qs = qs.filter(showtimes__starts_at__gt=timezone.now()).distinct()
        return qs

    @action(detail=True, methods=["get"], permission_classes=[AllowAny], url_path="poster.svg", url_name="poster")
    def poster(self, request, slug=None):
        response = HttpResponse(poster.render(self.get_object()), content_type="image/svg+xml")
        response["Cache-Control"] = "public, max-age=86400"
        return response


class GenreViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Genre.objects.all()
    serializer_class = GenreSerializer
    permission_classes = [AllowAny]
    pagination_class = None
    lookup_field = "slug"
