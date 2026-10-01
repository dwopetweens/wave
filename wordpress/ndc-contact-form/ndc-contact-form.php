<?php
/**
 * Plugin Name:       NDC Contact Form
 * Description:       Contact form for NDC Consulting Group with layered spam protection. Use the [ndc_contact_form] shortcode (Elementor: Shortcode widget).
 * Version:           1.1.0
 * Requires at least: 6.0
 * Requires PHP:      7.4
 * Author:            NDC Consulting Group
 * License:           GPL-2.0-or-later
 * Text Domain:       ndc-contact-form
 */

defined( 'ABSPATH' ) || exit;

final class NDC_Contact_Form {

	const VERSION          = '1.1.0';
	const OPTION           = 'ndc_contact_form';
	const POST_TYPE        = 'ndc_enquiry';
	const DEFAULT_TO       = 'nadiaworsley@gmail.com';
	const MIN_SECONDS      = 4;              // Faster than this is a bot.
	const MAX_TOKEN_AGE    = 7 * DAY_IN_SECONDS; // Tolerates page caching.
	const RATE_LIMIT       = 5;              // Submissions per IP per hour.
	const MAX_LINKS        = 2;              // URLs allowed in the message.
	const HONEYPOT         = 'ndc_website';  // Hidden field; humans leave it empty.

	/** @var array Per-request form state: errors + submitted values. */
	private static $state = array( 'errors' => array(), 'values' => array() );

	public static function init() {
		add_shortcode( 'ndc_contact_form', array( __CLASS__, 'render' ) );
		add_action( 'init', array( __CLASS__, 'register_post_type' ) );
		add_action( 'template_redirect', array( __CLASS__, 'handle_submission' ) );
		add_action( 'wp_enqueue_scripts', array( __CLASS__, 'register_assets' ) );
		add_action( 'admin_menu', array( __CLASS__, 'admin_menu' ) );
		add_action( 'admin_init', array( __CLASS__, 'register_settings' ) );
		add_filter( 'plugin_action_links_' . plugin_basename( __FILE__ ), array( __CLASS__, 'settings_link' ) );
	}

	/* ------------------------------------------------------------------ */
	/* Settings                                                            */
	/* ------------------------------------------------------------------ */

	public static function settings() {
		return wp_parse_args(
			get_option( self::OPTION, array() ),
			array(
				'recipient'            => self::DEFAULT_TO,
				'success_message'      => __( 'Thank you — your message has been sent. We will be in touch soon.', 'ndc-contact-form' ),
				'turnstile_site_key'   => '',
				'turnstile_secret_key' => '',
			)
		);
	}

	public static function register_settings() {
		register_setting(
			'ndc_contact_form',
			self::OPTION,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( __CLASS__, 'sanitize_settings' ),
			)
		);
	}

	public static function sanitize_settings( $input ) {
		$input = (array) $input;
		$out   = array();
		$emails = array_filter( array_map( 'sanitize_email', array_map( 'trim', explode( ',', (string) ( $input['recipient'] ?? '' ) ) ) ), 'is_email' );
		$out['recipient']            = $emails ? implode( ', ', $emails ) : self::DEFAULT_TO;
		$out['success_message']      = sanitize_text_field( $input['success_message'] ?? '' );
		$out['turnstile_site_key']   = sanitize_text_field( $input['turnstile_site_key'] ?? '' );
		$out['turnstile_secret_key'] = sanitize_text_field( $input['turnstile_secret_key'] ?? '' );
		return $out;
	}

	public static function admin_menu() {
		add_options_page(
			__( 'NDC Contact Form', 'ndc-contact-form' ),
			__( 'NDC Contact Form', 'ndc-contact-form' ),
			'manage_options',
			'ndc-contact-form',
			array( __CLASS__, 'settings_page' )
		);
	}

	public static function settings_link( $links ) {
		array_unshift( $links, '<a href="' . esc_url( admin_url( 'options-general.php?page=ndc-contact-form' ) ) . '">' . esc_html__( 'Settings', 'ndc-contact-form' ) . '</a>' );
		return $links;
	}

	public static function settings_page() {
		$s = self::settings();
		?>
		<div class="wrap">
			<h1><?php esc_html_e( 'NDC Contact Form', 'ndc-contact-form' ); ?></h1>
			<p><?php esc_html_e( 'Add the form to any page with the shortcode', 'ndc-contact-form' ); ?> <code>[ndc_contact_form]</code>.
				<?php esc_html_e( 'Every submission is also saved under', 'ndc-contact-form' ); ?>
				<a href="<?php echo esc_url( admin_url( 'edit.php?post_type=' . self::POST_TYPE ) ); ?>"><?php esc_html_e( 'Enquiries', 'ndc-contact-form' ); ?></a>.</p>
			<form method="post" action="options.php">
				<?php settings_fields( 'ndc_contact_form' ); ?>
				<table class="form-table" role="presentation">
					<tr>
						<th scope="row"><label for="ndc-recipient"><?php esc_html_e( 'Send enquiries to', 'ndc-contact-form' ); ?></label></th>
						<td><input id="ndc-recipient" class="regular-text" type="text" name="<?php echo esc_attr( self::OPTION ); ?>[recipient]" value="<?php echo esc_attr( $s['recipient'] ); ?>">
							<p class="description"><?php esc_html_e( 'Separate several addresses with commas.', 'ndc-contact-form' ); ?></p></td>
					</tr>
					<tr>
						<th scope="row"><label for="ndc-success"><?php esc_html_e( 'Success message', 'ndc-contact-form' ); ?></label></th>
						<td><input id="ndc-success" class="large-text" type="text" name="<?php echo esc_attr( self::OPTION ); ?>[success_message]" value="<?php echo esc_attr( $s['success_message'] ); ?>"></td>
					</tr>
					<tr>
						<th scope="row"><?php esc_html_e( 'Cloudflare Turnstile (optional)', 'ndc-contact-form' ); ?></th>
						<td>
							<p><label><?php esc_html_e( 'Site key', 'ndc-contact-form' ); ?><br><input class="regular-text" type="text" name="<?php echo esc_attr( self::OPTION ); ?>[turnstile_site_key]" value="<?php echo esc_attr( $s['turnstile_site_key'] ); ?>"></label></p>
							<p><label><?php esc_html_e( 'Secret key', 'ndc-contact-form' ); ?><br><input class="regular-text" type="password" autocomplete="off" name="<?php echo esc_attr( self::OPTION ); ?>[turnstile_secret_key]" value="<?php echo esc_attr( $s['turnstile_secret_key'] ); ?>"></label></p>
							<p class="description"><?php esc_html_e( 'The form already blocks most bots without this. Add free Turnstile keys from dash.cloudflare.com if spam still gets through.', 'ndc-contact-form' ); ?></p>
						</td>
					</tr>
				</table>
				<?php submit_button(); ?>
			</form>
		</div>
		<?php
	}

	/* ------------------------------------------------------------------ */
	/* Storage                                                             */
	/* ------------------------------------------------------------------ */

	public static function register_post_type() {
		register_post_type(
			self::POST_TYPE,
			array(
				'labels'          => array(
					'name'          => __( 'Enquiries', 'ndc-contact-form' ),
					'singular_name' => __( 'Enquiry', 'ndc-contact-form' ),
				),
				'public'          => false,
				'show_ui'         => true,
				'menu_icon'       => 'dashicons-email-alt',
				'supports'        => array( 'title', 'editor' ),
				'capability_type' => 'post',
				'capabilities'    => array( 'create_posts' => 'do_not_allow' ),
				'map_meta_cap'    => true,
			)
		);
	}

	/* ------------------------------------------------------------------ */
	/* Front end                                                           */
	/* ------------------------------------------------------------------ */

	public static function register_assets() {
		$url = plugin_dir_url( __FILE__ );
		wp_register_style( 'ndc-contact-form', $url . 'assets/form.css', array(), self::VERSION );
		wp_register_script( 'ndc-contact-form', $url . 'assets/form.js', array(), self::VERSION, true );
		wp_register_script( 'cf-turnstile', 'https://challenges.cloudflare.com/turnstile/v0/api.js', array(), null, true ); // phpcs:ignore WordPress.WP.EnqueuedResourceParameters.MissingVersion
	}

	/** Signed, time-stamped token that proves the form was rendered by this site. */
	private static function make_token() {
		$ts = time();
		return $ts . '.' . substr( wp_hash( 'ndc-contact|' . $ts ), 0, 20 );
	}

	private static function check_token( $token ) {
		if ( ! is_string( $token ) || ! preg_match( '/^(\d{10})\.([a-f0-9]{20})$/', $token, $m ) ) {
			return false;
		}
		$age = time() - (int) $m[1];
		return hash_equals( substr( wp_hash( 'ndc-contact|' . $m[1] ), 0, 20 ), $m[2] )
			&& $age >= 0 && $age <= self::MAX_TOKEN_AGE;
	}

	public static function render() {
		$s = self::settings();
		wp_enqueue_style( 'ndc-contact-form' );
		wp_enqueue_script( 'ndc-contact-form' );

		if ( isset( $_GET['ndc_sent'] ) ) { // phpcs:ignore WordPress.Security.NonceVerification.Recommended
			return '<div class="ndc-form ndc-form--sent" id="ndc-contact" role="status"><p class="ndc-form__success">' . esc_html( $s['success_message'] ) . '</p></div>';
		}

		$errors = self::$state['errors'];
		$v      = self::$state['values'] + array_fill_keys( array( 'first_name', 'last_name', 'company', 'email', 'message' ), '' );
		$turnstile = $s['turnstile_site_key'] && $s['turnstile_secret_key'];
		if ( $turnstile ) {
			wp_enqueue_script( 'cf-turnstile' );
		}

		$field = static function ( $name, $label, $type, $autocomplete, $placeholder = '' ) use ( $errors, $v ) {
			$id    = 'ndc-' . str_replace( '_', '-', $name );
			$error = $errors[ $name ] ?? '';
			$attrs = sprintf(
				'id="%1$s" name="%2$s" required aria-required="true" autocomplete="%3$s"%4$s%5$s',
				esc_attr( $id ),
				esc_attr( $name ),
				esc_attr( $autocomplete ),
				$placeholder ? ' placeholder="' . esc_attr( $placeholder ) . '"' : '',
				$error ? ' aria-invalid="true" aria-describedby="' . esc_attr( $id ) . '-error"' : ''
			);
			if ( 'textarea' === $type ) {
				$control = '<textarea ' . $attrs . ' rows="6" maxlength="5000">' . esc_textarea( $v[ $name ] ) . '</textarea>';
			} else {
				$control = '<input type="' . esc_attr( $type ) . '" ' . $attrs . ' maxlength="200" value="' . esc_attr( $v[ $name ] ) . '">';
			}
			$html = '';
			if ( $label ) {
				$html .= '<label class="ndc-form__label" for="' . esc_attr( $id ) . '">' . esc_html( $label ) . ' <span class="ndc-form__req" aria-hidden="true">*</span></label>';
			}
			$html .= $control;
			if ( $error ) {
				$html .= '<p class="ndc-form__error" id="' . esc_attr( $id ) . '-error">' . esc_html( $error ) . '</p>';
			}
			return $html;
		};

		ob_start();
		?>
		<form class="ndc-form" id="ndc-contact" method="post" action="#ndc-contact" novalidate>
			<?php if ( ! empty( $errors['_form'] ) ) : ?>
				<p class="ndc-form__alert" role="alert"><?php echo esc_html( $errors['_form'] ); ?></p>
			<?php elseif ( $errors ) : ?>
				<p class="ndc-form__alert" role="alert"><?php esc_html_e( 'Please fix the highlighted fields and try again.', 'ndc-contact-form' ); ?></p>
			<?php endif; ?>

			<fieldset class="ndc-form__row ndc-form__row--full">
				<legend class="ndc-form__label"><?php esc_html_e( 'Full Name', 'ndc-contact-form' ); ?> <span class="ndc-form__req" aria-hidden="true">*</span></legend>
				<div class="ndc-form__pair">
					<div><label class="screen-reader-text" for="ndc-first-name"><?php esc_html_e( 'First Name', 'ndc-contact-form' ); ?></label><?php echo $field( 'first_name', '', 'text', 'given-name', __( 'First Name', 'ndc-contact-form' ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></div>
					<div><label class="screen-reader-text" for="ndc-last-name"><?php esc_html_e( 'Last Name', 'ndc-contact-form' ); ?></label><?php echo $field( 'last_name', '', 'text', 'family-name', __( 'Last Name', 'ndc-contact-form' ) ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></div>
				</div>
			</fieldset>

			<div class="ndc-form__row"><?php echo $field( 'company', __( 'Company / Organization', 'ndc-contact-form' ), 'text', 'organization' ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></div>
			<div class="ndc-form__row"><?php echo $field( 'email', __( 'Email', 'ndc-contact-form' ), 'email', 'email' ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></div>
			<div class="ndc-form__row ndc-form__row--full"><?php echo $field( 'message', __( 'Tell us more about the scope of work, including your goals, desired outcomes, and specific services you are seeking.', 'ndc-contact-form' ), 'textarea', 'off' ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped ?></div>

			<?php // Honeypot: hidden from people and screen readers; bots fill it in. ?>
			<div class="ndc-form__hp" aria-hidden="true">
				<label for="ndc-website">Website</label>
				<input type="text" id="ndc-website" name="<?php echo esc_attr( self::HONEYPOT ); ?>" value="" tabindex="-1" autocomplete="off">
			</div>
			<input type="hidden" name="ndc_token" value="<?php echo esc_attr( self::make_token() ); ?>">
			<input type="hidden" name="ndc_js" value="">
			<input type="hidden" name="ndc_contact_submit" value="1">

			<?php if ( $turnstile ) : ?>
				<div class="ndc-form__row ndc-form__row--full">
					<div class="cf-turnstile" data-sitekey="<?php echo esc_attr( $s['turnstile_site_key'] ); ?>"></div>
					<?php if ( ! empty( $errors['turnstile'] ) ) : ?>
						<p class="ndc-form__error"><?php echo esc_html( $errors['turnstile'] ); ?></p>
					<?php endif; ?>
				</div>
			<?php endif; ?>

			<div class="ndc-form__row ndc-form__row--full">
				<button type="submit" class="ndc-form__submit"><?php esc_html_e( 'Send Message', 'ndc-contact-form' ); ?></button>
			</div>
		</form>
		<?php
		return ob_get_clean();
	}

	/* ------------------------------------------------------------------ */
	/* Submission handling                                                 */
	/* ------------------------------------------------------------------ */

	private static function client_ip() {
		return isset( $_SERVER['REMOTE_ADDR'] ) ? sanitize_text_field( wp_unslash( $_SERVER['REMOTE_ADDR'] ) ) : '';
	}

	/** Pretend success to bots so they get no signal to adapt to. */
	private static function silent_reject( $reason ) {
		do_action( 'ndc_contact_form_blocked', $reason );
		self::redirect_success();
	}

	private static function redirect_success() {
		$page = get_queried_object_id() ? get_permalink( get_queried_object_id() ) : home_url( '/' );
		$url  = remove_query_arg( 'ndc_sent', wp_get_referer() ?: $page );
		wp_safe_redirect( add_query_arg( 'ndc_sent', '1', $url ) . '#ndc-contact' );
		exit;
	}

	public static function handle_submission() {
		// phpcs:disable WordPress.Security.NonceVerification.Missing -- guarded by the signed token below; nonces break on cached pages.
		if ( 'POST' !== ( $_SERVER['REQUEST_METHOD'] ?? '' ) || empty( $_POST['ndc_contact_submit'] ) ) {
			return;
		}

		$post = wp_unslash( $_POST );

		// 1. Honeypot.
		if ( ! empty( $post[ self::HONEYPOT ] ) ) {
			self::silent_reject( 'honeypot' );
		}

		// 2. Signed render token: must exist, be genuine, and not be ancient.
		$token = (string) ( $post['ndc_token'] ?? '' );
		if ( ! self::check_token( $token ) ) {
			self::silent_reject( 'token' );
		}

		// 3. JavaScript proof + time trap. The script echoes the token back only
		//    after a real key press or tap, and only after MIN_SECONDS.
		$js = (string) ( $post['ndc_js'] ?? '' );
		if ( ! hash_equals( 'ok:' . $token, $js ) ) {
			self::silent_reject( 'no-js' );
		}
		if ( time() - (int) $token < self::MIN_SECONDS ) {
			self::silent_reject( 'too-fast' );
		}

		// 4. Per-IP rate limit.
		$ip       = self::client_ip();
		$rate_key = 'ndc_cf_rate_' . md5( $ip );
		$count    = (int) get_transient( $rate_key );
		if ( $count >= self::RATE_LIMIT ) {
			self::$state['errors']['_form'] = __( 'Too many messages from your connection. Please try again in an hour.', 'ndc-contact-form' );
			return;
		}

		// Collect and validate.
		$values = array(
			'first_name' => sanitize_text_field( $post['first_name'] ?? '' ),
			'last_name'  => sanitize_text_field( $post['last_name'] ?? '' ),
			'company'    => sanitize_text_field( $post['company'] ?? '' ),
			'email'      => sanitize_email( $post['email'] ?? '' ),
			'message'    => sanitize_textarea_field( $post['message'] ?? '' ),
		);
		self::$state['values'] = $values;

		$errors = array();
		$labels = array(
			'first_name' => __( 'Please enter your first name.', 'ndc-contact-form' ),
			'last_name'  => __( 'Please enter your last name.', 'ndc-contact-form' ),
			'company'    => __( 'Please enter your company or organization.', 'ndc-contact-form' ),
			'email'      => __( 'Please enter your email address.', 'ndc-contact-form' ),
			'message'    => __( 'Please tell us a little about what you need.', 'ndc-contact-form' ),
		);
		foreach ( $labels as $key => $msg ) {
			if ( '' === trim( $values[ $key ] ) ) {
				$errors[ $key ] = $msg;
			}
		}
		if ( empty( $errors['email'] ) && ! is_email( $values['email'] ) ) {
			$errors['email'] = __( 'Please enter a valid email address.', 'ndc-contact-form' );
		}
		if ( empty( $errors['message'] ) && mb_strlen( trim( $values['message'] ) ) < 20 ) {
			$errors['message'] = __( 'Please add a little more detail (at least 20 characters).', 'ndc-contact-form' );
		}

		// 5. Content checks typical of spam.
		if ( empty( $errors['message'] ) ) {
			$links = preg_match_all( '~(https?://|www\.)~i', $values['message'] . ' ' . $values['company'] );
			if ( $links > self::MAX_LINKS ) {
				$errors['message'] = __( 'Please include no more than two links.', 'ndc-contact-form' );
			} elseif ( preg_match( '~\[url[=\]]|<a\s+href~i', $post['message'] ?? '' ) ) {
				self::silent_reject( 'markup' );
			}
		}
		foreach ( array( 'first_name', 'last_name' ) as $key ) {
			if ( empty( $errors[ $key ] ) && preg_match( '~https?://|www\.|@~i', $values[ $key ] ) ) {
				self::silent_reject( 'name-link' );
			}
		}
		// Respects Settings → Discussion → "Disallowed Comment Keys".
		if ( ! $errors && function_exists( 'wp_check_comment_disallowed_list' ) &&
			wp_check_comment_disallowed_list( $values['first_name'] . ' ' . $values['last_name'], $values['email'], '', $values['message'] . "\n" . $values['company'], $ip, $_SERVER['HTTP_USER_AGENT'] ?? '' ) ) {
			self::silent_reject( 'disallowed' );
		}

		// 6. Optional Cloudflare Turnstile.
		$s = self::settings();
		if ( ! $errors && $s['turnstile_site_key'] && $s['turnstile_secret_key'] ) {
			$resp = wp_remote_post(
				'https://challenges.cloudflare.com/turnstile/v0/siteverify',
				array(
					'timeout' => 10,
					'body'    => array(
						'secret'   => $s['turnstile_secret_key'],
						'response' => (string) ( $post['cf-turnstile-response'] ?? '' ),
						'remoteip' => $ip,
					),
				)
			);
			$ok = ! is_wp_error( $resp ) && ! empty( json_decode( wp_remote_retrieve_body( $resp ), true )['success'] );
			if ( ! $ok ) {
				$errors['turnstile'] = __( 'Please complete the verification and try again.', 'ndc-contact-form' );
			}
		}
		// phpcs:enable

		if ( $errors ) {
			self::$state['errors'] = $errors;
			return;
		}

		set_transient( $rate_key, $count + 1, HOUR_IN_SECONDS );
		self::deliver( $values, $s );
		self::redirect_success();
	}

	private static function deliver( array $v, array $s ) {
		$name    = trim( $v['first_name'] . ' ' . $v['last_name'] );
		$subject = sprintf( 'New enquiry from %s (%s)', $name, $v['company'] );
		$body    = implode(
			"\n",
			array(
				'Name:     ' . $name,
				'Company:  ' . $v['company'],
				'Email:    ' . $v['email'],
				'',
				'Message:',
				$v['message'],
				'',
				'—',
				'Sent from ' . home_url( '/' ) . ' on ' . wp_date( 'j F Y, g:i a' ),
			)
		);

		// Keep a copy in WordPress so nothing is lost if email delivery fails.
		$post_id = wp_insert_post(
			array(
				'post_type'    => self::POST_TYPE,
				'post_status'  => 'private',
				'post_title'   => $subject,
				'post_content' => $body,
			)
		);

		// Newlines are stripped from names by sanitize_text_field, so the header is safe.
		$headers = array(
			'Content-Type: text/plain; charset=UTF-8',
			sprintf( 'Reply-To: %s <%s>', str_replace( array( '<', '>', '"' ), '', $name ), $v['email'] ),
		);
		$sent = wp_mail( array_map( 'trim', explode( ',', $s['recipient'] ) ), $subject, $body, $headers );
		if ( $post_id && ! is_wp_error( $post_id ) ) {
			update_post_meta( $post_id, '_ndc_email_sent', $sent ? 'yes' : 'no' );
			update_post_meta( $post_id, '_ndc_reply_to', $v['email'] );
		}
	}
}

NDC_Contact_Form::init();
