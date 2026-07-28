# Local Jekyll development server only. CI builds the site with
# ruby/setup-ruby, not this image.
FROM ruby:3.1

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential nodejs libffi-dev zlib1g-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /site

RUN gem install bundler:2.4.19
RUN bundle config force_ruby_platform true

COPY Gemfile Gemfile.lock* ./
RUN bundle install

EXPOSE 4000
CMD ["bundle", "exec", "jekyll", "serve", "--livereload", "--host", "0.0.0.0"]
